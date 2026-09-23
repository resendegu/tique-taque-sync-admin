"""Regressão das duas rajadas de notificação observadas em produção.

Evidência que motivou estes testes (namespace `resende`, 22-23/09/2026):

* pod subiu às 17:45 BRT e mandou 4 DMs em 1 segundo — as batidas daquela hora,
  reanunciadas porque o SQLite (efêmero) perdeu a deduplicação no reinício;
* à 00:00 BRT saíram 8 DMs em 3 segundos — a jornada inteira do dia anterior,
  porque a chave de deduplicação inclui a data e tudo virou "inédito".
"""

import asyncio
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import pytz

from src.database.db import AdminDatabase
from src.engine.scheduler import AdminSyncScheduler
from src.engine.workday import WorkdayEngine
from src.tiquetaque.models import AdminEmployee

TZ = pytz.timezone("America/Sao_Paulo")
FUNCIONARIO = "emp-teste"
BATIDAS_DE_ONTEM = ["07:58", "13:50", "14:50", "17:01"]


class BotFalso:
    """Registra o que teria ido para o Slack, sem sair da máquina."""

    def __init__(self):
        self.enviados = []

    async def send_dm_to_employee(self, employee_id, email, title, message, **kwargs):
        self.enviados.append(title)
        return True


class TestRajadasDeAlerta(unittest.TestCase):
    def setUp(self):
        # ignore_cleanup_errors: no Windows o SQLite mantém o arquivo preso
        # até o processo sair, e isso não é o que este teste avalia.
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)

        self.bot = BotFalso()
        self.db = AdminDatabase(Path(self._tmp.name) / "t.db")
        self.db.upsert_employees_from_api([
            AdminEmployee(id=FUNCIONARIO, full_name="Fulano", email="f@e.com")
        ])
        self.scheduler = AdminSyncScheduler(
            client=None,
            engine=WorkdayEngine(timezone_name="America/Sao_Paulo"),
            database=self.db,
            bot=self.bot,
            timezone_name="America/Sao_Paulo",
        )

    def _rodar_em(self, momento: datetime) -> list[str]:
        self.bot.enviados.clear()
        with mock.patch("src.engine.scheduler.datetime") as fake:
            fake.now.return_value = momento
            asyncio.run(self.scheduler._evaluate_and_dispatch_alerts())
        return list(self.bot.enviados)

    def test_virada_do_dia_nao_reanuncia_a_jornada_anterior(self):
        """À 00:00, o cache é de ontem: nada deve ser anunciado."""
        self.scheduler._cached_punches = {FUNCIONARIO: BATIDAS_DE_ONTEM}
        self.scheduler._cached_punches_date = "22/09/2026"

        enviados = self._rodar_em(TZ.localize(datetime(2026, 9, 23, 0, 0, 12)))

        self.assertEqual(enviados, [], "a jornada de ontem foi reanunciada à meia-noite")
        self.assertEqual(self.scheduler._cached_punches, {}, "o cache vencido deveria ser descartado")

    def test_reinicio_no_meio_do_dia_nao_reanuncia_batidas_passadas(self):
        """Pod sobe às 17:45 com o banco vazio: as batidas do dia já passaram."""
        self.scheduler._cached_punches = {FUNCIONARIO: BATIDAS_DE_ONTEM}
        self.scheduler._cached_punches_date = "23/09/2026"

        enviados = self._rodar_em(TZ.localize(datetime(2026, 9, 23, 17, 45)))

        self.assertEqual(enviados, [], "batidas antigas foram reanunciadas após o reinício")

    def test_batida_recente_ainda_e_anunciada(self):
        """A proteção não pode emudecer o caso normal: batida de agora avisa."""
        self.scheduler._cached_punches = {FUNCIONARIO: ["07:58"]}
        self.scheduler._cached_punches_date = "23/09/2026"

        enviados = self._rodar_em(TZ.localize(datetime(2026, 9, 23, 8, 0)))

        self.assertEqual(len(enviados), 1, "a batida recém-feita deveria ser anunciada")

    def test_alertas_vencidos_ficam_registrados_para_nao_voltarem(self):
        """Silenciar não é ignorar: o alerta é gravado como despachado."""
        self.scheduler._cached_punches = {FUNCIONARIO: BATIDAS_DE_ONTEM}
        self.scheduler._cached_punches_date = "23/09/2026"
        self._rodar_em(TZ.localize(datetime(2026, 9, 23, 17, 45)))

        for indice, batida in enumerate(BATIDAS_DE_ONTEM):
            with self.subTest(batida=batida):
                self.assertTrue(
                    self.db.has_alert_been_sent(FUNCIONARIO, "23/09/2026", f"punch_{indice}_{batida}"),
                    "o alerta silenciado precisa ficar registrado",
                )

    def test_sync_company_completes_without_error(self):
        """sync_company deve rodar sem NameError ou exceção de variáveis não declaradas."""
        fake_client = mock.AsyncMock()
        fake_client.get_employees.return_value = [
            AdminEmployee(id=FUNCIONARIO, full_name="Fulano", email="f@e.com")
        ]
        fake_client.get_employee_times.return_value = ["08:00", "12:00"]
        self.scheduler.client = fake_client

        asyncio.run(self.scheduler.sync_company())

        self.assertIn(FUNCIONARIO, self.scheduler._cached_punches)
        self.assertIsNotNone(self.scheduler._cached_punches_date)
        self.assertIn(FUNCIONARIO, self.scheduler._cached_status)


if __name__ == "__main__":
    unittest.main()
