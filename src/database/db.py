"""SQLite database with WAL mode for TiqueTaque Sync Admin."""

import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime
import pytz

from ..tiquetaque.models import AdminEmployee

logger = logging.getLogger(__name__)


class AdminDatabase:
    """Manages SQLite storage for employee preferences, alert tracking, and company policy."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            # Company Policy Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS company_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)

            # Employees & Preferences Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS employees (
                    id TEXT PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    email TEXT,
                    timezone TEXT DEFAULT 'America/Sao_Paulo',
                    notifications_enabled INTEGER DEFAULT 1,
                    lunch_warning_advance_minutes INTEGER,
                    end_work_warning_advance_minutes INTEGER,
                    continuous_work_warning_advance_minutes INTEGER,
                    slack_user_id TEXT,
                    updated_at TEXT NOT NULL
                );
            """)

            # Dispatched Alerts Table (Deduplication)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dispatched_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    alert_type TEXT NOT NULL,
                    sent_at TEXT NOT NULL,
                    UNIQUE(employee_id, date, alert_type)
                );
            """)

            # Audit / Sync Logs
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    status TEXT NOT NULL,
                    details TEXT
                );
            """)

    # --------------------------------------------------------------------------
    # Company Settings & Policies
    # --------------------------------------------------------------------------
    def get_company_setting(self, key: str, default: str | None = None) -> str | None:
        with self._get_connection() as conn:
            row = conn.execute("SELECT value FROM company_settings WHERE key = ?;", (key,)).fetchone()
            return row["value"] if row else default

    def set_company_setting(self, key: str, value: str):
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO company_settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value;
            """, (key, value))

    def get_all_company_settings(self) -> dict[str, str]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT key, value FROM company_settings;").fetchall()
            return {r["key"]: r["value"] for r in rows}

    # --------------------------------------------------------------------------
    # Employee Management
    # --------------------------------------------------------------------------
    def upsert_employees_from_api(
        self,
        employees: list[AdminEmployee],
        default_lunch: int = 10,
        default_end: int = 15,
        default_clt: int = 10
    ):
        """Sync employees from TiqueTaque API into local database.

        Preserves existing notification toggle and custom alert preferences.
        """
        now_iso = datetime.now(pytz.utc).isoformat()
        with self._get_connection() as conn:
            for emp in employees:
                conn.execute("""
                    INSERT INTO employees (
                        id, full_name, email, timezone, notifications_enabled,
                        lunch_warning_advance_minutes, end_work_warning_advance_minutes,
                        continuous_work_warning_advance_minutes, updated_at
                    ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        full_name = excluded.full_name,
                        email = excluded.email,
                        timezone = excluded.timezone,
                        updated_at = excluded.updated_at;
                """, (
                    emp.id, emp.full_name, emp.email, emp.timezone,
                    default_lunch, default_end, default_clt, now_iso
                ))

    def get_all_employees(self) -> list[dict]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM employees ORDER BY full_name ASC;").fetchall()
            return [dict(r) for r in rows]

    def get_employee(self, employee_id: str) -> dict | None:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM employees WHERE id = ?;", (employee_id,)).fetchone()
            return dict(row) if row else None

    def get_employee_by_email(self, email: str) -> dict | None:
        if not email:
            return None
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM employees WHERE LOWER(email) = LOWER(?);", (email.strip(),)).fetchone()
            return dict(row) if row else None

    def update_employee_toggle(self, employee_id: str, enabled: bool):
        now_iso = datetime.now(pytz.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE employees SET notifications_enabled = ?, updated_at = ? WHERE id = ?;",
                (1 if enabled else 0, now_iso, employee_id)
            )

    def update_employee_slack_id(self, employee_id: str, slack_user_id: str):
        now_iso = datetime.now(pytz.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE employees SET slack_user_id = ?, updated_at = ? WHERE id = ?;",
                (slack_user_id, now_iso, employee_id)
            )

    def update_employee_preferences(
        self,
        employee_id: str,
        lunch_minutes: int | None = None,
        end_work_minutes: int | None = None,
        clt_minutes: int | None = None
    ):
        now_iso = datetime.now(pytz.utc).isoformat()
        updates = []
        params = []
        if lunch_minutes is not None:
            updates.append("lunch_warning_advance_minutes = ?")
            params.append(lunch_minutes)
        if end_work_minutes is not None:
            updates.append("end_work_warning_advance_minutes = ?")
            params.append(end_work_minutes)
        if clt_minutes is not None:
            updates.append("continuous_work_warning_advance_minutes = ?")
            params.append(clt_minutes)

        if not updates:
            return

        updates.append("updated_at = ?")
        params.append(now_iso)
        params.append(employee_id)

        sql = f"UPDATE employees SET {', '.join(updates)} WHERE id = ?;"
        with self._get_connection() as conn:
            conn.execute(sql, params)

    # --------------------------------------------------------------------------
    # Dispatched Alerts Deduplication
    # --------------------------------------------------------------------------
    def has_alert_been_sent(self, employee_id: str, date_str: str, alert_type: str) -> bool:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM dispatched_alerts WHERE employee_id = ? AND date = ? AND alert_type = ?;",
                (employee_id, date_str, alert_type)
            ).fetchone()
            return row is not None

    def record_dispatched_alert(self, employee_id: str, date_str: str, alert_type: str):
        now_iso = datetime.now(pytz.utc).isoformat()
        with self._get_connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO dispatched_alerts (employee_id, date, alert_type, sent_at) VALUES (?, ?, ?, ?);",
                    (employee_id, date_str, alert_type, now_iso)
                )
            except sqlite3.IntegrityError:
                pass

    def clear_dispatched_alert(self, employee_id: str, date_str: str, alert_type: str | None = None):
        """Remove dispatched alert record to allow re-testing of specific alerts."""
        with self._get_connection() as conn:
            if alert_type:
                conn.execute(
                    "DELETE FROM dispatched_alerts WHERE employee_id = ? AND date = ? AND alert_type = ?;",
                    (employee_id, date_str, alert_type)
                )
            else:
                conn.execute(
                    "DELETE FROM dispatched_alerts WHERE employee_id = ? AND date = ?;",
                    (employee_id, date_str)
                )

    # --------------------------------------------------------------------------
    # Backup Export & Import (JSON)
    # --------------------------------------------------------------------------
    def export_config_backup(self) -> dict:
        """Export all company settings and employee notification preferences to JSON dict."""
        settings = self.get_all_company_settings()
        employees = self.get_all_employees()
        return {
            "version": "1.0",
            "exported_at": datetime.now(pytz.utc).isoformat(),
            "company_settings": settings,
            "employees": [
                {
                    "id": emp["id"],
                    "full_name": emp["full_name"],
                    "email": emp["email"],
                    "notifications_enabled": bool(emp["notifications_enabled"]),
                    "lunch_warning_advance_minutes": emp["lunch_warning_advance_minutes"],
                    "end_work_warning_advance_minutes": emp["end_work_warning_advance_minutes"],
                    "continuous_work_warning_advance_minutes": emp["continuous_work_warning_advance_minutes"],
                    "slack_user_id": emp["slack_user_id"],
                }
                for emp in employees
            ]
        }

    def import_config_backup(self, backup_data: dict) -> dict:
        """Restore company settings and employee preferences from JSON backup."""
        imported_settings = backup_data.get("company_settings", {})
        imported_employees = backup_data.get("employees", [])

        # Restore company settings
        for k, v in imported_settings.items():
            self.set_company_setting(k, str(v))

        restored_count = 0
        now_iso = datetime.now(pytz.utc).isoformat()
        with self._get_connection() as conn:
            for emp in imported_employees:
                conn.execute("""
                    INSERT INTO employees (
                        id, full_name, email, notifications_enabled,
                        lunch_warning_advance_minutes, end_work_warning_advance_minutes,
                        continuous_work_warning_advance_minutes, slack_user_id, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        notifications_enabled = excluded.notifications_enabled,
                        lunch_warning_advance_minutes = excluded.lunch_warning_advance_minutes,
                        end_work_warning_advance_minutes = excluded.end_work_warning_advance_minutes,
                        continuous_work_warning_advance_minutes = excluded.continuous_work_warning_advance_minutes,
                        slack_user_id = COALESCE(excluded.slack_user_id, employees.slack_user_id),
                        updated_at = excluded.updated_at;
                """, (
                    emp["id"], emp["full_name"], emp.get("email"),
                    1 if emp.get("notifications_enabled", True) else 0,
                    emp.get("lunch_warning_advance_minutes"),
                    emp.get("end_work_warning_advance_minutes"),
                    emp.get("continuous_work_warning_advance_minutes"),
                    emp.get("slack_user_id"),
                    now_iso
                ))
                restored_count += 1

        return {
            "restored_settings_count": len(imported_settings),
            "restored_employees_count": restored_count,
        }
