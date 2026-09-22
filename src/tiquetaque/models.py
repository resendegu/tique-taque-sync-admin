"""Pydantic models for TiqueTaque Public Admin API (v2.1)."""

from typing import Any
from pydantic import BaseModel, Field


class ContractData(BaseModel):
    records_start_date: str | None = None
    hour_rate_cents: int | None = None
    payment_source: str | None = None
    allow_web_record: bool = True
    allow_app_record: bool = True
    allow_external_api_record: bool = True
    allow_access_app: bool = True


class AdminEmployee(BaseModel):
    id: str = Field(alias="_id")
    full_name: str
    email: str | None = None
    timezone: str = "America/Sao_Paulo"
    work_schedule: str | None = None
    city: str | None = None
    state: str | None = None
    contract_data: ContractData | dict[str, Any] | None = None

    class Config:
        populate_by_name = True


class TimeRecord(BaseModel):
    time: str  # ISO format e.g. 2026-09-21T14:51
    approved: bool = False
    type: str | None = "web"
    justification: str | None = None

    @property
    def time_str(self) -> str:
        """Extract HH:mm from ISO time string."""
        if "T" in self.time:
            return self.time.split("T")[1][:5]
        return self.time[:5]


class EmployeeTimesResponse(BaseModel):
    employee_id: str
    times: list[TimeRecord] = []


class WorkSchedule(BaseModel):
    id: str = Field(alias="_id")
    description: str

    class Config:
        populate_by_name = True
