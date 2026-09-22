"""Asynchronous polling scheduler and fast alert ticker for company-wide employees."""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional
import pytz

from .workday import WorkdayEngine, EmployeeWorkdayStatus, WorkdayStage
from ..tiquetaque.client import TiqueTaqueAdminClient
from ..database.db import AdminDatabase
from ..slack.bot import SlackBot

logger = logging.getLogger(__name__)


class AdminSyncScheduler:
    """Orchestrates batch polling from TiqueTaque API and fast local evaluation for alerts."""

    def __init__(
        self,
        client: TiqueTaqueAdminClient,
        engine: WorkdayEngine,
        database: AdminDatabase,
        bot: SlackBot,
        poll_interval_seconds: int = 180,
        alert_ticker_interval_seconds: int = 15,
        timezone_name: str = "America/Sao_Paulo",
    ):
        self.client = client
        self.engine = engine
        self.db = database
        self.bot = bot
        self.poll_interval = poll_interval_seconds
        self.ticker_interval = alert_ticker_interval_seconds
        self.tz = pytz.timezone(timezone_name)

        self._poll_task: Optional[asyncio.Task] = None
        self._ticker_task: Optional[asyncio.Task] = None
        self._running = False

        # In-memory cache of latest punches per employee: {emp_id: ["08:00", "12:00"]}
        self._cached_punches: Dict[str, List[str]] = {}
        # In-memory simulation override for punches testing: {emp_id: ["14:00", "18:00", "19:15"]}
        self._punches_override: Dict[str, List[str]] = {}
        # In-memory cache of latest workday status: {emp_id: EmployeeWorkdayStatus}
        self._cached_status: Dict[str, EmployeeWorkdayStatus] = {}

    async def start(self):
        """Start the dual-loop workers."""
        if self._running:
            return
        self._running = True
        logger.info(
            "Starting AdminSyncScheduler: poll=%ds, ticker=%ds",
            self.poll_interval, self.ticker_interval
        )
        # Initial poll immediately
        await self.sync_company()
        self._poll_task = asyncio.create_task(self._poll_loop())
        self._ticker_task = asyncio.create_task(self._ticker_loop())

    async def stop(self):
        """Gracefully stop workers."""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
        if self._ticker_task:
            self._ticker_task.cancel()
        logger.info("AdminSyncScheduler stopped.")

    async def sync_company(self):
        """Synchronize all employees and their daily punches from TiqueTaque Public Admin API."""
        try:
            logger.info("Starting company-wide sync with TiqueTaque API...")
            employees = await self.client.get_employees()
            if not employees:
                logger.warning("No employees returned from TiqueTaque API.")
                return

            # Upsert into database preserving existing employee toggles & preferences
            self.db.upsert_employees_from_api(employees)

            today_str = datetime.now(self.tz).strftime("%Y-%m-%d")
            stored_employees = self.db.get_all_employees()

            default_lead = int(self.db.get_company_setting("default_lead_time", "10"))
            for emp in stored_employees:
                emp_id = emp["id"]
                # Even if notifications are disabled, we track punches for dashboard visibility
                if emp_id in self._punches_override:
                    punches = self._punches_override[emp_id]
                else:
                    punches = await self.client.get_employee_times(emp_id, today_str)
                self._cached_punches[emp_id] = punches

                lead = emp.get("lunch_warning_advance_minutes") or default_lead
                status = self.engine.calculate(
                    employee_id=emp_id,
                    times=punches,
                    lunch_advance_minutes=lead,
                    end_work_advance_minutes=lead,
                    clt_advance_minutes=lead,
                )
                self._cached_status[emp_id] = status

            logger.info("Company sync complete for %d employees.", len(stored_employees))
        except Exception as e:
            logger.exception("Error during company sync: %s", e)

    async def _poll_loop(self):
        """Periodic background worker to refresh punches from TiqueTaque API."""
        while self._running:
            try:
                await asyncio.sleep(self.poll_interval)
                await self.sync_company()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Unexpected error in poll loop: %s", e)

    async def _ticker_loop(self):
        """High-frequency (15s) worker to evaluate minute-by-minute alert countdowns."""
        while self._running:
            try:
                await asyncio.sleep(self.ticker_interval)
                await self._evaluate_and_dispatch_alerts()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Unexpected error in ticker loop: %s", e)

    async def _evaluate_and_dispatch_alerts(self):
        """Check all employees in memory and trigger Slack notifications when conditions are met."""
        now = datetime.now(self.tz)
        today_date_str = now.strftime("%d/%m/%Y")
        allow_customization = self.db.get_company_setting("allow_employee_customization", "true") == "true"
        default_lead = int(self.db.get_company_setting("default_lead_time", "10"))
        stored_employees = self.db.get_all_employees()

        for emp in stored_employees:
            emp_id = emp["id"]
            if not emp.get("notifications_enabled"):
                continue  # Company or employee disabled notifications for this person

            punches = self._cached_punches.get(emp_id, [])
            lead = emp.get("lunch_warning_advance_minutes") or default_lead
            lunch_adv = lead
            end_adv = lead
            clt_adv = lead

            status = self.engine.calculate(
                employee_id=emp_id,
                times=punches,
                current_dt=now,
                lunch_advance_minutes=lead,
                end_work_advance_minutes=lead,
                clt_advance_minutes=lead,
            )
            self._cached_status[emp_id] = status

            # 1. Lunch Advance Alert
            if status.lunch_advance_alert and not self.db.has_alert_been_sent(emp_id, today_date_str, "lunch_advance"):
                rem_min = max(1, (status.remaining_lunch_seconds or 0) // 60)
                await self.bot.send_dm_to_employee(
                    employee_id=emp_id,
                    email=emp.get("email"),
                    title="Aviso de Término do Almoço",
                    message=(
                        f"Olá *{emp['full_name']}*, faltam aproximadamente *{rem_min} minutos* para completar seu intervalo padrão de 1 hora de almoço. "
                        "Prepare-se para registrar seu retorno ao trabalho! 🍽️"
                    ),
                    stage_text="Em Almoço",
                    level="info",
                    allow_customization=allow_customization,
                    advance_minutes=lunch_adv,
                )
                self.db.record_dispatched_alert(emp_id, today_date_str, "lunch_advance")

            # 2. Lunch Final Alert (1 min remaining)
            if status.lunch_final_alert and not self.db.has_alert_been_sent(emp_id, today_date_str, "lunch_final"):
                await self.bot.send_dm_to_employee(
                    employee_id=emp_id,
                    email=emp.get("email"),
                    title="Atenção: 1 Minuto para o Fim do Almoço!",
                    message=(
                        f"*{emp['full_name']}*, seu intervalo de 1 hora está a *1 minuto de se completar*. "
                        "Não se esqueça de registrar seu retorno no TiqueTaque para manter seu ponto em dia! ⏱️"
                    ),
                    stage_text="Último Minuto de Almoço",
                    level="warning",
                    allow_customization=allow_customization,
                    advance_minutes=lunch_adv,
                )
                self.db.record_dispatched_alert(emp_id, today_date_str, "lunch_final")

            # 3. CLT Continuous Work Warning (10 min prior to 6h)
            if status.clt_advance_alert and not self.db.has_alert_been_sent(emp_id, today_date_str, "clt_6h_advance"):
                await self.bot.send_dm_to_employee(
                    employee_id=emp_id,
                    email=emp.get("email"),
                    title="Alerta CLT Art. 71 — Pausa Obrigatória Próxima",
                    message=(
                        f"*{emp['full_name']}*, você já trabalhou *{status.continuous_hours_str}* contínuos sem intervalo. "
                        f"Pelo Artigo 71 da CLT, é obrigatória uma pausa ao atingir 6h de trabalho contínuo. "
                        f"Faltam aproximadamente *{clt_adv} minutos* para esse limite. Programe seu intervalo de descanso ou almoço agora! ⚠️"
                    ),
                    stage_text="Limite CLT se Aproximando",
                    level="warning",
                    allow_customization=allow_customization,
                    advance_minutes=clt_adv,
                )
                self.db.record_dispatched_alert(emp_id, today_date_str, "clt_6h_advance")

            # 4. CLT Continuous Work Final Alert (1 min prior to 6h)
            if status.clt_final_alert and not self.db.has_alert_been_sent(emp_id, today_date_str, "clt_6h_final"):
                await self.bot.send_dm_to_employee(
                    employee_id=emp_id,
                    email=emp.get("email"),
                    title="🚨 CRÍTICO: 1 Minuto para Limite Legal CLT (6h Contínuas)!",
                    message=(
                        f"*{emp['full_name']}*, falta apenas *1 minuto* para completar 6 horas de trabalho ininterrupto sem pausa. "
                        "Interrompa suas atividades e registre sua pausa imediatamente conforme as diretrizes trabalhistas da CLT! 🛑"
                    ),
                    stage_text="Limite Legal CLT Excedendo",
                    level="critical",
                    allow_customization=allow_customization,
                    advance_minutes=clt_adv,
                )
                self.db.record_dispatched_alert(emp_id, today_date_str, "clt_6h_final")

            # 5. End of Work Advance Warning
            if status.end_work_advance_alert and not self.db.has_alert_been_sent(emp_id, today_date_str, "end_work_advance"):
                rem_min = max(1, (status.remaining_work_seconds or 0) // 60)
                await self.bot.send_dm_to_employee(
                    employee_id=emp_id,
                    email=emp.get("email"),
                    title="Encerramento de Expediente se Aproximando",
                    message=(
                        f"*{emp['full_name']}*, sua jornada de 8 horas está chegando ao fim! "
                        f"Faltam aproximadamente *{rem_min} minutos*. Horário previsto de saída: *{status.estimated_end_time}*. "
                        "Vá finalizando suas tarefas do dia! 🎉"
                    ),
                    stage_text="Turno da Tarde",
                    level="info",
                    allow_customization=allow_customization,
                    advance_minutes=end_adv,
                )
                self.db.record_dispatched_alert(emp_id, today_date_str, "end_work_advance")

            # 6. End of Work Final Warning (1 min remaining)
            if status.end_work_final_alert and not self.db.has_alert_been_sent(emp_id, today_date_str, "end_work_final"):
                await self.bot.send_dm_to_employee(
                    employee_id=emp_id,
                    email=emp.get("email"),
                    title="1 Minuto para o Fim da Jornada!",
                    message=(
                        f"*{emp['full_name']}*, falta apenas *1 minuto* para atingir sua meta de 8 horas de trabalho hoje. "
                        "Bata seu ponto de encerramento no TiqueTaque para finalizar seu dia sem horas extras indesejadas! 🏁"
                    ),
                    stage_text="Fim de Expediente",
                    level="success",
                    allow_customization=allow_customization,
                    advance_minutes=end_adv,
                )
                self.db.record_dispatched_alert(emp_id, today_date_str, "end_work_final")

            # 7. Summary Alert (When workday completed)
            if status.summary_alert and not self.db.has_alert_been_sent(emp_id, today_date_str, "summary"):
                await self.bot.send_dm_to_employee(
                    employee_id=emp_id,
                    email=emp.get("email"),
                    title="Jornada Concluída com Sucesso!",
                    message=(
                        f"Parabéns *{emp['full_name']}*, seu expediente foi encerrado! Total líquido trabalhado hoje: *{status.worked_hours_str}*. "
                        f"Duração do almoço: *{status.lunch_duration_str}*. Batidas registradas: `{', '.join(status.times)}`. "
                        "Tenha um excelente descanso! 🚀"
                    ),
                    stage_text="Jornada Concluída",
                    level="success",
                    allow_customization=allow_customization,
                    advance_minutes=end_adv,
                )
                self.db.record_dispatched_alert(emp_id, today_date_str, "summary")

    def get_status_for_employee(self, employee_id: str) -> Optional[EmployeeWorkdayStatus]:
        return self._cached_status.get(employee_id)
