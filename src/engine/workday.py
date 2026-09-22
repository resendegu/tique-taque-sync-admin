"""Workday calculation engine and CLT compliance tracking for employees."""

from datetime import datetime, time, timedelta
from enum import Enum
from typing import List, Optional
import pytz


class WorkdayStage(str, Enum):
    NOT_STARTED = "not_started"
    FIRST_HALF = "first_half"
    LUNCH_BREAK = "lunch_break"
    SECOND_HALF = "second_half"
    COMPLETED = "completed"


class EmployeeWorkdayStatus:
    def __init__(
        self,
        employee_id: str,
        stage: WorkdayStage,
        worked_seconds: int,
        continuous_worked_seconds: int,
        lunch_duration_seconds: int,
        remaining_lunch_seconds: Optional[int],
        remaining_work_seconds: Optional[int],
        estimated_end_time: Optional[str],
        times: List[str],
        lunch_advance_alert: bool = False,
        lunch_final_alert: bool = False,
        end_work_advance_alert: bool = False,
        end_work_final_alert: bool = False,
        clt_advance_alert: bool = False,
        clt_final_alert: bool = False,
        summary_alert: bool = False,
    ):
        self.employee_id = employee_id
        self.stage = stage
        self.worked_seconds = worked_seconds
        self.continuous_worked_seconds = continuous_worked_seconds
        self.lunch_duration_seconds = lunch_duration_seconds
        self.remaining_lunch_seconds = remaining_lunch_seconds
        self.remaining_work_seconds = remaining_work_seconds
        self.estimated_end_time = estimated_end_time
        self.times = times
        self.lunch_advance_alert = lunch_advance_alert
        self.lunch_final_alert = lunch_final_alert
        self.end_work_advance_alert = end_work_advance_alert
        self.end_work_final_alert = end_work_final_alert
        self.clt_advance_alert = clt_advance_alert
        self.clt_final_alert = clt_final_alert
        self.summary_alert = summary_alert

    @property
    def worked_hours_str(self) -> str:
        h = self.worked_seconds // 3600
        m = (self.worked_seconds % 3600) // 60
        return f"{h:02d}h{m:02d}m"

    @property
    def continuous_hours_str(self) -> str:
        h = self.continuous_worked_seconds // 3600
        m = (self.continuous_worked_seconds % 3600) // 60
        return f"{h:02d}h{m:02d}m"

    @property
    def lunch_duration_str(self) -> str:
        m = self.lunch_duration_seconds // 60
        return f"{m} min"

    def to_dict(self) -> dict:
        return {
            "employee_id": self.employee_id,
            "stage": self.stage.value,
            "worked_seconds": self.worked_seconds,
            "worked_hours_str": self.worked_hours_str,
            "continuous_worked_seconds": self.continuous_worked_seconds,
            "continuous_hours_str": self.continuous_hours_str,
            "lunch_duration_seconds": self.lunch_duration_seconds,
            "lunch_duration_str": self.lunch_duration_str,
            "remaining_lunch_seconds": self.remaining_lunch_seconds,
            "remaining_work_seconds": self.remaining_work_seconds,
            "estimated_end_time": self.estimated_end_time,
            "times": self.times,
        }


class WorkdayEngine:
    """Calculates status, predictions, and alerts for an employee based on their punches."""

    def __init__(
        self,
        target_hours: float = 8.0,
        lunch_duration_minutes: int = 60,
        continuous_work_limit_hours: float = 6.0,
        lunch_warning_final_minutes: int = 1,
        end_work_warning_final_minutes: int = 1,
        continuous_work_warning_final_minutes: int = 1,
        timezone_name: str = "America/Sao_Paulo",
    ):
        self.target_hours = target_hours
        self.target_seconds = int(target_hours * 3600)
        self.lunch_target_seconds = int(lunch_duration_minutes * 60)
        self.continuous_limit_seconds = int(continuous_work_limit_hours * 3600)
        self.lunch_final_sec = lunch_warning_final_minutes * 60
        self.end_work_final_sec = end_work_warning_final_minutes * 60
        self.clt_final_sec = continuous_work_warning_final_minutes * 60
        self.tz = pytz.timezone(timezone_name)

    def _parse_time_str(self, t_str: str, base_date: datetime) -> datetime:
        parts = t_str.split(":")
        h = int(parts[0])
        m = int(parts[1])
        s = int(parts[2]) if len(parts) > 2 else 0
        dt = base_date.replace(hour=h, minute=m, second=s, microsecond=0)
        return dt

    def calculate(
        self,
        employee_id: str,
        times: List[str],
        current_dt: Optional[datetime] = None,
        lunch_advance_minutes: int = 10,
        end_work_advance_minutes: int = 15,
        clt_advance_minutes: int = 10,
    ) -> EmployeeWorkdayStatus:
        now = current_dt or datetime.now(self.tz)
        base_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        clean_times = sorted([t.strip() for t in times if t.strip()])
        dts = [self._parse_time_str(t, base_date) for t in clean_times]

        lunch_advance_sec = lunch_advance_minutes * 60
        end_work_advance_sec = end_work_advance_minutes * 60
        clt_advance_sec = clt_advance_minutes * 60

        # Case 0: Not Started
        if not dts:
            return EmployeeWorkdayStatus(
                employee_id=employee_id,
                stage=WorkdayStage.NOT_STARTED,
                worked_seconds=0,
                continuous_worked_seconds=0,
                lunch_duration_seconds=0,
                remaining_lunch_seconds=None,
                remaining_work_seconds=self.target_seconds,
                estimated_end_time=None,
                times=[],
            )

        # Case 1: First Half (1 punch)
        if len(dts) == 1:
            start = dts[0]
            worked = max(0, int((now - start).total_seconds())) if now > start else 0
            continuous = worked
            remaining_work = max(0, self.target_seconds - worked)

            clt_advance = (self.continuous_limit_seconds - continuous) <= clt_advance_sec and continuous < self.continuous_limit_seconds
            clt_final = (self.continuous_limit_seconds - continuous) <= self.clt_final_sec and continuous < self.continuous_limit_seconds

            return EmployeeWorkdayStatus(
                employee_id=employee_id,
                stage=WorkdayStage.FIRST_HALF,
                worked_seconds=worked,
                continuous_worked_seconds=continuous,
                lunch_duration_seconds=0,
                remaining_lunch_seconds=None,
                remaining_work_seconds=remaining_work,
                estimated_end_time=None,
                times=clean_times,
                clt_advance_alert=clt_advance,
                clt_final_alert=clt_final,
            )

        # Case 2: Lunch Break (2 punches)
        if len(dts) == 2:
            morning_start = dts[0]
            lunch_start = dts[1]
            worked = max(0, int((lunch_start - morning_start).total_seconds()))
            lunch_duration = max(0, int((now - lunch_start).total_seconds())) if now > lunch_start else 0
            remaining_lunch = max(0, self.lunch_target_seconds - lunch_duration)
            remaining_work = max(0, self.target_seconds - worked)

            # Alerts for lunch end
            lunch_advance = remaining_lunch <= lunch_advance_sec and remaining_lunch > self.lunch_final_sec
            lunch_final = remaining_lunch <= self.lunch_final_sec and lunch_duration < (self.lunch_target_seconds + 300)

            return EmployeeWorkdayStatus(
                employee_id=employee_id,
                stage=WorkdayStage.LUNCH_BREAK,
                worked_seconds=worked,
                continuous_worked_seconds=0,
                lunch_duration_seconds=lunch_duration,
                remaining_lunch_seconds=remaining_lunch,
                remaining_work_seconds=remaining_work,
                estimated_end_time=None,
                times=clean_times,
                lunch_advance_alert=lunch_advance,
                lunch_final_alert=lunch_final,
            )

        # Case 3: Second Half (3 punches)
        if len(dts) == 3:
            morning_start = dts[0]
            lunch_start = dts[1]
            afternoon_start = dts[2]

            morning_worked = max(0, int((lunch_start - morning_start).total_seconds()))
            lunch_duration = max(0, int((afternoon_start - lunch_start).total_seconds()))
            afternoon_worked = max(0, int((now - afternoon_start).total_seconds())) if now > afternoon_start else 0

            total_worked = morning_worked + afternoon_worked
            continuous = afternoon_worked
            remaining_work = max(0, self.target_seconds - total_worked)

            # Calculate exact predicted exit time
            est_end_dt = afternoon_start + timedelta(seconds=max(0, self.target_seconds - morning_worked))
            est_end_str = est_end_dt.strftime("%H:%M")

            end_work_advance = remaining_work <= end_work_advance_sec and remaining_work > self.end_work_final_sec
            end_work_final = remaining_work <= self.end_work_final_sec and remaining_work > 0

            clt_advance = (self.continuous_limit_seconds - continuous) <= clt_advance_sec and continuous < self.continuous_limit_seconds
            clt_final = (self.continuous_limit_seconds - continuous) <= self.clt_final_sec and continuous < self.continuous_limit_seconds

            return EmployeeWorkdayStatus(
                employee_id=employee_id,
                stage=WorkdayStage.SECOND_HALF,
                worked_seconds=total_worked,
                continuous_worked_seconds=continuous,
                lunch_duration_seconds=lunch_duration,
                remaining_lunch_seconds=0,
                remaining_work_seconds=remaining_work,
                estimated_end_time=est_end_str,
                times=clean_times,
                end_work_advance_alert=end_work_advance,
                end_work_final_alert=end_work_final,
                clt_advance_alert=clt_advance,
                clt_final_alert=clt_final,
            )

        # Case 4: Completed (4 or more punches)
        total_worked = 0
        continuous = 0
        for i in range(0, len(dts) - 1, 2):
            seg = max(0, int((dts[i + 1] - dts[i]).total_seconds()))
            total_worked += seg

        lunch_duration = 0
        if len(dts) >= 4:
            lunch_duration = max(0, int((dts[2] - dts[1]).total_seconds()))

        return EmployeeWorkdayStatus(
            employee_id=employee_id,
            stage=WorkdayStage.COMPLETED,
            worked_seconds=total_worked,
            continuous_worked_seconds=0,
            lunch_duration_seconds=lunch_duration,
            remaining_lunch_seconds=0,
            remaining_work_seconds=0,
            estimated_end_time=dts[-1].strftime("%H:%M"),
            times=clean_times,
            summary_alert=True,
        )
