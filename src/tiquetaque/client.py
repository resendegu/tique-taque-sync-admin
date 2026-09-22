"""HTTP Client for TiqueTaque Public Admin API (v2.1)."""

import base64
import logging
import httpx

from .models import AdminEmployee, EmployeeTimesResponse, WorkSchedule

logger = logging.getLogger(__name__)


class TiqueTaqueAdminClient:
    """Async client interacting with TiqueTaque's Public Admin API using BasicAuth."""

    def __init__(self, token: str, base_url: str = "https://api.tiquetaque.com/v2.1"):
        self.token = token.strip()
        self.base_url = base_url.rstrip("/")
        # TiqueTaque Public Admin API uses HTTP BasicAuth: username 'public', password is the token
        auth_bytes = f"public:{self.token}".encode("utf-8")
        self._auth_header = f"Basic {base64.b64encode(auth_bytes).decode('utf-8')}"

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": self._auth_header,
                "Accept": "application/json",
                "User-Agent": "TiqueTaque-Sync-Admin/1.0",
            },
            timeout=15.0,
        )

    async def get_employees(self) -> list[AdminEmployee]:
        """Fetch all active company employees."""
        logger.info("Fetching employees from TiqueTaque Public Admin API...")
        resp = await self._client.get("/employees")
        if resp.status_code != 200:
            logger.error("Failed to fetch employees: HTTP %s - %s", resp.status_code, resp.text)
            resp.raise_for_status()

        data = resp.json()
        raw_items = data.get("_items", [])
        employees = [AdminEmployee.model_validate(item) for item in raw_items]
        logger.info("Retrieved %d employees successfully.", len(employees))
        return employees

    async def get_employee_times(self, employee_id: str, date_str: str) -> list[str]:
        """Fetch times for a specific employee on a given date (YYYY-MM-DD).

        Returns list of HH:mm string punches (e.g. ['08:00', '12:00', '13:00']).
        """
        params = {
            "employee_id": employee_id,
            "start_date": date_str,
            "end_date": date_str,
        }
        resp = await self._client.get("/times", params=params)
        if resp.status_code != 200:
            logger.warning(
                "Failed to fetch times for employee %s on %s: HTTP %s - %s",
                employee_id, date_str, resp.status_code, resp.text
            )
            return []

        data = resp.json()
        parsed = EmployeeTimesResponse.model_validate(data)
        # Extract and sort HH:mm strings
        time_strings = sorted([t.time_str for t in parsed.times])
        return time_strings

    async def get_work_schedules(self) -> list[WorkSchedule]:
        """Fetch work schedules summary."""
        resp = await self._client.get("/work-schedules/summary")
        if resp.status_code != 200:
            logger.warning("Failed to fetch work schedules: HTTP %s", resp.status_code)
            return []
        data = resp.json()
        raw_items = data.get("_items", [])
        return [WorkSchedule.model_validate(item) for item in raw_items]

    async def close(self):
        await self._client.aclose()
