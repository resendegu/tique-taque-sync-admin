"""Tests for Slack Block Kit message generation and interaction parsing."""

import unittest
import tempfile
from pathlib import Path

from src.slack.blocks import build_workday_notification_blocks
from src.slack.interactions import handle_slack_interaction
from src.database.db import AdminDatabase
from src.tiquetaque.models import AdminEmployee


class TestSlackBot(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = AdminDatabase(Path(self.temp_dir.name) / "test_slack.db")
        emp = AdminEmployee(_id="emp123", full_name="Lucas Rocha", email="lucas@empresa.com")
        self.db.upsert_employees_from_api([emp])
        self.db.update_employee_slack_id("emp123", "U12345678")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_block_kit_builder(self):
        # With employee customization enabled
        blocks = build_workday_notification_blocks(
            title="Aviso de Almoço",
            message="Faltam 10 minutos",
            stage_text="Em Almoço",
            allow_customization=True,
            current_advance_minutes=10,
        )
        self.assertTrue(any(b.get("type") == "actions" for b in blocks))

        # With employee customization disabled by company policy
        blocks_no_custom = build_workday_notification_blocks(
            title="Aviso de Almoço",
            message="Faltam 10 minutos",
            stage_text="Em Almoço",
            allow_customization=False,
        )
        self.assertFalse(any(b.get("type") == "actions" for b in blocks_no_custom))

    def test_interaction_set_lead_time(self):
        payload = {
            "user": {"id": "U12345678"},
            "actions": [
                {"action_id": "set_lead_time_5", "value": "5"}
            ]
        }
        res = handle_slack_interaction(payload, self.db)
        self.assertIn("Preferência atualizada", res["text"])

        # Check in DB
        emp = self.db.get_employee("emp123")
        self.assertEqual(emp["lunch_warning_advance_minutes"], 5)

    def test_interaction_mute_alerts(self):
        payload = {
            "user": {"id": "U12345678"},
            "actions": [
                {"action_id": "mute_alerts", "value": "mute"}
            ]
        }
        res = handle_slack_interaction(payload, self.db)
        self.assertIn("silenciadas com sucesso", res["text"])

        # Check in DB
        emp = self.db.get_employee("emp123")
        self.assertEqual(emp["notifications_enabled"], 0)

    def test_interaction_blocked_when_customization_disabled(self):
        # Disable customization in company settings
        self.db.set_company_setting("allow_employee_customization", "false")

        payload = {
            "user": {"id": "U12345678"},
            "actions": [
                {"action_id": "set_lead_time_15", "value": "15"}
            ]
        }
        res = handle_slack_interaction(payload, self.db)
        self.assertIn("desativados pelas diretrizes da sua empresa", res["text"])

        # Verify DB was NOT updated (still original 10, not 15)
        emp = self.db.get_employee("emp123")
        self.assertEqual(emp["lunch_warning_advance_minutes"], 10)


if __name__ == "__main__":
    unittest.main()
