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
                # Fetch official punches from TiqueTaque Public Admin API
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

            # Evaluate alerts immediately following fresh API data sync
            await self._evaluate_and_dispatch_alerts()
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
            # 0. Instant Punch Confirmation Alerts (dispatched when a new punch is registered in TiqueTaque)
            base_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            for idx, p_time in enumerate(punches):
                alert_key = f"punch_{idx}_{p_time}"
                if not self.db.has_alert_been_sent(emp_id, today_date_str, alert_key):
                    try:
                        p_parts = p_time.split(":")
                        p_dt = base_date.replace(
                            hour=int(p_parts[0]),
                            minute=int(p_parts[1]),
                            second=int(p_parts[2]) if len(p_parts) > 2 else 0,
                        )
                    except Exception:
                        p_dt = now

                    # Avoid spamming old history on cold start / pod restart if older than 1 hour
                    if (now - p_dt).total_seconds() > 3600:
                        self.db.record_dispatched_alert(emp_id, today_date_str, alert_key)
                        continue

                    if idx == 0:
                        p_title = f"✅ Ponto Registrado: Entrada às {p_time}"
                        p_msg = (
                            f"Olá *{emp['full_name']}*, seu registro de *Entrada* às *{p_time}* foi confirmado no TiqueTaque! "
                            "Tenha um excelente dia de trabalho! 🚀"
                        )
                        p_stage = "Entrada Registrada"
                        p_level = "success"
                    elif idx == 1:
                        # 1º Intervalo / Almoço
                        try:
                            t_in = base_date.replace(hour=int(punches[0].split(":")[0]), minute=int(punches[0].split(":")[1]))
                            p1_worked = max(0, int((p_dt - t_in).total_seconds()))
                            p1_h = p1_worked // 3600
                            p1_m = (p1_worked % 3600) // 60
                            p1_str = f"{p1_h:02d}h{p1_m:02d}m"
                        except Exception:
                            p1_str = None

                        break_est_return = (p_dt + timedelta(hours=1)).strftime("%H:%M")
                        p_title = f"☕ Ponto Registrado: Saída para Intervalo às {p_time}"
                        worked_info = f"\n• Horas trabalhadas no período: *{p1_str}*" if p1_str else ""
                        p_msg = (
                            f"*{emp['full_name']}*, sua saída para intervalo foi confirmada às *{p_time}*.\n\n"
                            f"📊 *Informações do Intervalo:*{worked_info}\n"
                            f"• Retorno previsto (padrão de 1 hora): *{break_est_return}*\n\n"
                            "Bom descanso! ☕🥪"
                        )
                        p_stage = "Saída para Intervalo"
                        p_level = "info"
                    elif idx == 2:
                        est_end = status.estimated_end_time or "Horário padrão"
                        p_title = f"⏱️ Ponto Registrado: Retorno do Intervalo às {p_time}"
                        p_msg = (
                            f"*{emp['full_name']}*, seu retorno do intervalo foi confirmado às *{p_time}* "
                            f"(intervalo de *{status.lunch_duration_str}*). Horário previsto para encerramento do expediente: *{est_end}*. "
                            "Bom retorno ao trabalho! 💼"
                        )
                        p_stage = "Retorno do Intervalo"
                        p_level = "info"
                    elif idx % 2 == 1:
                        # Todo registro de saída adicional (batidas 4, 6...): contém as horas totais trabalhadas do dia
                        worked_up_to_punch = 0
                        for i in range(0, idx, 2):
                            try:
                                t_in = base_date.replace(hour=int(punches[i].split(":")[0]), minute=int(punches[i].split(":")[1]))
                                t_out = base_date.replace(hour=int(punches[i+1].split(":")[0]), minute=int(punches[i+1].split(":")[1]))
                                worked_up_to_punch += max(0, int((t_out - t_in).total_seconds()))
                            except Exception:
                                pass

                        w_h = worked_up_to_punch // 3600
                        w_m = (worked_up_to_punch % 3600) // 60
                        worked_str = f"{w_h:02d}h{w_m:02d}m"

                        target_sec = int(self.workday_engine.target_hours * 3600)
                        break_est_return = (p_dt + timedelta(hours=1)).strftime("%H:%M")

                        if worked_up_to_punch >= target_sec:
                            p_title = f"🏁 Ponto Registrado: Saída às {p_time}"
                            p_msg = (
                                f"*{emp['full_name']}*, seu registro de *Saída* foi confirmado às *{p_time}*!\n\n"
                                f"📊 *Resumo da Jornada:*\n"
                                f"• Meta diária de 8h cumprida!\n"
                                f"• Total de horas trabalhadas no dia: *{worked_str}*.\n\n"
                                f"Tenha um excelente descanso!"
                            )
                            p_stage = "Saída Registrada"
                            p_level = "success"
                            self.db.record_dispatched_alert(emp_id, today_date_str, "summary")
                        else:
                            rem_sec = max(0, target_sec - worked_up_to_punch)
                            rem_h = rem_sec // 3600
                            rem_m = (rem_sec % 3600) // 60
                            rem_str = f"{rem_h:02d}h{rem_m:02d}m"

                            p_title = f"⏱️ Ponto Registrado: Saída / Pausa às {p_time}"
                            p_msg = (
                                f"*{emp['full_name']}*, seu registro de *Saída* foi confirmado às *{p_time}*.\n\n"
                                f"📊 *Resumo da Jornada até aqui:*\n"
                                f"• Total de horas trabalhadas no dia: *{worked_str}*\n"
                                f"• Saldo restante para a meta (8h): *{rem_str}*\n"
                                f"• Retorno previsto (pausa padrão de 1h): *{break_est_return}*\n\n"
                                f"Bom descanso! Não se esqueça de registrar seu retorno no TiqueTaque quando voltar. ☕"
                            )
                            p_stage = f"Saída / Pausa #{idx // 2 + 1}"
                            p_level = "info"
                    else:
                        # Retorno de pausa adicional (batidas 5, 7...)
                        try:
                            prev_parts = punches[idx - 1].split(":")
                            prev_dt = base_date.replace(hour=int(prev_parts[0]), minute=int(prev_parts[1]))
                            pause_sec = max(0, int((p_dt - prev_dt).total_seconds()))
                            pause_str = f"{pause_sec // 60} min"
                        except Exception:
                            pause_str = "—"

                        est_end = status.estimated_end_time or "Horário padrão"
                        p_title = f"⏱️ Ponto Registrado: Retorno às {p_time}"
                        p_msg = (
                            f"*{emp['full_name']}*, seu retorno foi confirmado às *{p_time}* "
                            f"(intervalo de *{pause_str}*). "
                            f"Horário previsto para encerramento da jornada: *{est_end}*. "
                            "Bom retorno ao trabalho! 💼"
                        )
                        p_stage = f"Retorno #{idx // 2 + 1}"
                        p_level = "info"

                    await self.bot.send_dm_to_employee(
                        employee_id=emp_id,
                        email=emp.get("email"),
                        title=p_title,
                        message=p_msg,
                        stage_text=p_stage,
                        level=p_level,
                        allow_customization=False,
                    )
                    self.db.record_dispatched_alert(emp_id, today_date_str, alert_key)

            # Break Alert Keys: support multi-break tracking (break 1, break 2, etc.)
            break_num = len(punches) // 2
            if break_num <= 1:
                alert_key_adv = "lunch_advance"
                alert_key_fin = "lunch_final"
                alert_key_2h_adv = "lunch_2h_advance"
                alert_key_2h_fin = "lunch_2h_final"
            else:
                alert_key_adv = f"break_{break_num}_advance"
                alert_key_fin = f"break_{break_num}_final"
                alert_key_2h_adv = f"break_{break_num}_2h_advance"
                alert_key_2h_fin = f"break_{break_num}_2h_final"

            # 1. Break Advance Alert (10 min prior to 1h)
            if status.lunch_advance_alert and not self.db.has_alert_been_sent(emp_id, today_date_str, alert_key_adv):
                rem_min = max(1, (status.remaining_lunch_seconds or 0) // 60)
                await self.bot.send_dm_to_employee(
                    employee_id=emp_id,
                    email=emp.get("email"),
                    title="Aviso de Término do Intervalo",
                    message=(
                        f"Olá *{emp['full_name']}*, faltam aproximadamente *{rem_min} minutos* para completar seu intervalo previsto de 1 hora. "
                        "Prepare-se para registrar seu retorno ao trabalho! ⏱️"
                    ),
                    stage_text="Em Intervalo",
                    level="info",
                    allow_customization=allow_customization,
                    advance_minutes=lunch_adv,
                )
                self.db.record_dispatched_alert(emp_id, today_date_str, alert_key_adv)

            # 2. Break Final Alert (1 min remaining)
            if status.lunch_final_alert and not self.db.has_alert_been_sent(emp_id, today_date_str, alert_key_fin):
                await self.bot.send_dm_to_employee(
                    employee_id=emp_id,
                    email=emp.get("email"),
                    title="Atenção: 1 Minuto para o Fim do Intervalo!",
                    message=(
                        f"*{emp['full_name']}*, seu intervalo previsto de 1 hora está a *1 minuto de se completar*. "
                        "Não se esqueça de registrar seu retorno no TiqueTaque para manter seu ponto em dia! ⏱️"
                    ),
                    stage_text="Último Minuto de Intervalo",
                    level="warning",
                    allow_customization=allow_customization,
                    advance_minutes=lunch_adv,
                )
                self.db.record_dispatched_alert(emp_id, today_date_str, alert_key_fin)

            # 2.1. Extended Break Advance Alert (approaching 2h)
            if status.lunch_2h_advance_alert and not self.db.has_alert_been_sent(emp_id, today_date_str, alert_key_2h_adv):
                rem_min_2h = max(1, (status.remaining_lunch_2h_seconds or 0) // 60)
                await self.bot.send_dm_to_employee(
                    employee_id=emp_id,
                    email=emp.get("email"),
                    title="⚠️ Aviso de Intervalo Prolongado (Próximo de 2h)",
                    message=(
                        f"*{emp['full_name']}*, seu intervalo já tem *{status.lunch_duration_str}* decorridos. "
                        f"Faltam aproximadamente *{rem_min_2h} minutos* para completar 2 horas. "
                        "Não se esqueça de registrar seu ponto ao retornar!"
                    ),
                    stage_text="Intervalo Estendido",
                    level="warning",
                    allow_customization=allow_customization,
                    advance_minutes=lunch_adv,
                )
                self.db.record_dispatched_alert(emp_id, today_date_str, alert_key_2h_adv)

            # 2.2. Extended Break Final Alert (1 min remaining of 2h limit)
            if status.lunch_2h_final_alert and not self.db.has_alert_been_sent(emp_id, today_date_str, alert_key_2h_fin):
                await self.bot.send_dm_to_employee(
                    employee_id=emp_id,
                    email=emp.get("email"),
                    title="🚨 Atenção: 1 Minuto para completar 2h de Intervalo!",
                    message=(
                        f"*{emp['full_name']}*, falta apenas *1 minuto* para completar 2 horas de intervalo. "
                        "Não esqueça de registrar seu ponto ao retornar!"
                    ),
                    stage_text="Limite de Intervalo",
                    level="critical",
                    allow_customization=allow_customization,
                    advance_minutes=lunch_adv,
                )
                self.db.record_dispatched_alert(emp_id, today_date_str, alert_key_2h_fin)

            # 3. CLT Continuous Work Warning (10 min prior to 6h)
            if status.clt_advance_alert and not self.db.has_alert_been_sent(emp_id, today_date_str, "clt_6h_advance"):
                await self.bot.send_dm_to_employee(
                    employee_id=emp_id,
                    email=emp.get("email"),
                    title="Alerta — Pausa Obrigatória Próxima",
                    message=(
                        f"*{emp['full_name']}*, você já trabalhou *{status.continuous_hours_str}* contínuos sem intervalo. "
                        f"Faltam aproximadamente *{clt_adv} minutos* para atingir o limite de 6 horas de trabalho contínuo. Programe seu intervalo de descanso ou almoço agora! ⚠️"
                    ),
                    stage_text="Limite de Trabalho Contínuo se Aproximando",
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
                    title="🚨 1 Minuto para Limite de Trabalho Contínuo!",
                    message=(
                        f"*{emp['full_name']}*, falta apenas *1 minuto* para completar 6 horas de trabalho ininterrupto sem pausa. "
                        "Interrompa suas atividades e registre sua pausa! 🛑"
                    ),
                    stage_text="Limite de Trabalho Contínuo Excedido",
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
                        "Não esqueça de registrar seu ponto!"
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
                        "Não esqueça de registrar seu ponto!"
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
                    title="Jornada Concluída",
                    message=(
                        f"*{emp['full_name']}*, seu total líquido trabalhado hoje foi: *{status.worked_hours_str}*. "
                        f"Duração do almoço: *{status.lunch_duration_str}*. Pontos registrados: `{', '.join(status.times)}`. "
                    ),
                    stage_text="Jornada Concluída",
                    level="success",
                    allow_customization=allow_customization,
                    advance_minutes=end_adv,
                )
                self.db.record_dispatched_alert(emp_id, today_date_str, "summary")

    def get_status_for_employee(self, employee_id: str) -> Optional[EmployeeWorkdayStatus]:
        return self._cached_status.get(employee_id)
