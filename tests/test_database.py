"""Tests for AdminDatabase and Backup Export/Import."""

import unittest
import tempfile
from pathlib import Path

from src.database.db import AdminDatabase
from src.tiquetaque.models import AdminEmployee


class TestAdminDatabase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "test_admin.db"
        self.db = AdminDatabase(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_upsert_and_retrieve_employees(self):
        emp1 = AdminEmployee(_id="emp1", full_name="João Silva", email="joao@empresa.com")
        emp2 = AdminEmployee(_id="emp2", full_name="Maria Santos", email="maria@empresa.com")

        self.db.upsert_employees_from_api([emp1, emp2])
        emps = self.db.get_all_employees()
        self.assertEqual(len(emps), 2)
        self.assertEqual(emps[0]["full_name"], "João Silva")

    def test_notification_toggle(self):
        emp = AdminEmployee(_id="emp1", full_name="Carlos Lima", email="carlos@empresa.com")
        self.db.upsert_employees_from_api([emp])

        # Default is enabled (1)
        self.assertEqual(self.db.get_employee("emp1")["notifications_enabled"], 1)

        # Toggle off
        self.db.update_employee_toggle("emp1", False)
        self.assertEqual(self.db.get_employee("emp1")["notifications_enabled"], 0)

        # Toggle on
        self.db.update_employee_toggle("emp1", True)
        self.assertEqual(self.db.get_employee("emp1")["notifications_enabled"], 1)

    def test_alert_deduplication(self):
        date_str = "21/09/2026"
        emp_id = "emp1"
        self.assertFalse(self.db.has_alert_been_sent(emp_id, date_str, "lunch_advance"))

        self.db.record_dispatched_alert(emp_id, date_str, "lunch_advance")
        self.assertTrue(self.db.has_alert_been_sent(emp_id, date_str, "lunch_advance"))

        # Other alert types remain unsent
        self.assertFalse(self.db.has_alert_been_sent(emp_id, date_str, "lunch_final"))

    def test_backup_export_and_import(self):
        emp = AdminEmployee(_id="emp1", full_name="Ana Paula", email="ana@empresa.com")
        self.db.upsert_employees_from_api([emp])
        self.db.update_employee_toggle("emp1", False)
        self.db.update_employee_preferences("emp1", lunch_minutes=5, end_work_minutes=5)
        self.db.set_company_setting("allow_employee_customization", "false")

        backup = self.db.export_config_backup()
        self.assertEqual(len(backup["employees"]), 1)
        self.assertEqual(backup["employees"][0]["notifications_enabled"], False)
        self.assertEqual(backup["employees"][0]["lunch_warning_advance_minutes"], 5)
        self.assertEqual(backup["company_settings"]["allow_employee_customization"], "false")

        # Restore into another database
        db2_path = Path(self.temp_dir.name) / "test_admin2.db"
        db2 = AdminDatabase(db2_path)
        res = db2.import_config_backup(backup)
        self.assertEqual(res["restored_employees_count"], 1)
        self.assertEqual(db2.get_company_setting("allow_employee_customization"), "false")
        self.assertEqual(db2.get_employee("emp1")["notifications_enabled"], 0)
        self.assertEqual(db2.get_employee("emp1")["lunch_warning_advance_minutes"], 5)


if __name__ == "__main__":
    unittest.main()
