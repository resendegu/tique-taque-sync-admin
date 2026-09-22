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
        lunch_2h_advance_alert: bool = False,
        lunch_2h_final_alert: bool = False,
        end_work_advance_alert: bool = False,
        end_work_final_alert: bool = False,
        clt_advance_alert: bool = False,
        clt_final_alert: bool = False,
        summary_alert: bool = False,
        remaining_lunch_2h_seconds: Optional[int] = None,
    ):
        self.employee_id = employee_id
        self.stage = stage
        self.worked_seconds = worked_seconds
        self.continuous_worked_seconds = continuous_worked_seconds
        self.lunch_duration_seconds = lunch_duration_seconds
        self.remaining_lunch_seconds = remaining_lunch_seconds
        self.remaining_lunch_2h_seconds = remaining_lunch_2h_seconds
        self.remaining_work_seconds = remaining_work_seconds
        self.estimated_end_time = estimated_end_time
        self.times = times
        self.lunch_advance_alert = lunch_advance_alert
        self.lunch_final_alert = lunch_final_alert
        self.lunch_2h_advance_alert = lunch_2h_advance_alert
        self.lunch_2h_final_alert = lunch_2h_final_alert
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

    @property
    def remaining_work_str(self) -> str:
        if self.remaining_work_seconds is None or self.remaining_work_seconds <= 0:
            return "00h00m"
        h = self.remaining_work_seconds // 3600
        m = (self.remaining_work_seconds % 3600) // 60
        return f"{h:02d}h{m:02d}m"

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
            "remaining_lunch_2h_seconds": self.remaining_lunch_2h_seconds,
            "remaining_work_seconds": self.remaining_work_seconds,
            "remaining_work_str": self.remaining_work_str,
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

        # Sum of completed work blocks: (0, 1), (2, 3), (4, 5)...
        completed_worked = sum(
            max(0, int((dts[i + 1] - dts[i]).total_seconds()))
            for i in range(0, len(dts) - 1, 2)
        )

        # Duration of last completed break (e.g. between 1 and 2, or 3 and 4)
        last_completed_break = 0
        if len(dts) >= 3:
            if len(dts) % 2 == 1:
                last_completed_break = max(0, int((dts[-1] - dts[-2]).total_seconds()))
            else:
                last_completed_break = max(0, int((dts[-2] - dts[-3]).total_seconds()))

        is_working = (len(dts) % 2 == 1)

        if is_working:
            # Active work session (1st punch, 3rd punch, 5th punch...)
            active_start = dts[-1]
            active_worked = max(0, int((now - active_start).total_seconds())) if now > active_start else 0
            total_worked = completed_worked + active_worked
            continuous = active_worked
            remaining_work = max(0, self.target_seconds - total_worked)

            # Predicted finish time to complete target_hours (8h)
            est_end_dt = active_start + timedelta(seconds=max(0, self.target_seconds - completed_worked))
            est_end_str = est_end_dt.strftime("%H:%M")

            end_work_advance = (remaining_work <= end_work_advance_sec and remaining_work > self.end_work_final_sec)
            end_work_final = (remaining_work <= self.end_work_final_sec and remaining_work > 0)

            clt_advance = (self.continuous_limit_seconds - continuous) <= clt_advance_sec and (self.continuous_limit_seconds - continuous) > self.clt_final_sec
            clt_final = (self.continuous_limit_seconds - continuous) <= self.clt_final_sec

            stage = WorkdayStage.FIRST_HALF if len(dts) == 1 else WorkdayStage.SECOND_HALF

            return EmployeeWorkdayStatus(
                employee_id=employee_id,
                stage=stage,
                worked_seconds=total_worked,
                continuous_worked_seconds=continuous,
                lunch_duration_seconds=last_completed_break,
                remaining_lunch_seconds=0,
                remaining_lunch_2h_seconds=0,
                remaining_work_seconds=remaining_work,
                estimated_end_time=est_end_str,
                times=clean_times,
                end_work_advance_alert=end_work_advance,
                end_work_final_alert=end_work_final,
                clt_advance_alert=clt_advance,
                clt_final_alert=clt_final,
            )

        else:
            # Clocked out (2, 4, 6... punches): either in break/pause or completed workday
            total_worked = completed_worked
            remaining_work = max(0, self.target_seconds - total_worked)

            # If 4+ punches AND target (8h) reached -> COMPLETED
            if len(dts) >= 4 and total_worked >= self.target_seconds:
                return EmployeeWorkdayStatus(
                    employee_id=employee_id,
                    stage=WorkdayStage.COMPLETED,
                    worked_seconds=total_worked,
                    continuous_worked_seconds=0,
                    lunch_duration_seconds=last_completed_break,
                    remaining_lunch_seconds=0,
                    remaining_lunch_2h_seconds=0,
                    remaining_work_seconds=0,
                    estimated_end_time=dts[-1].strftime("%H:%M"),
                    times=clean_times,
                    summary_alert=True,
                )

            # In active break / pause (break 1, break 2, etc.)
            break_start = dts[-1]
            break_duration = max(0, int((now - break_start).total_seconds())) if now > break_start else 0
            remaining_lunch = max(0, self.lunch_target_seconds - break_duration)

            # 1h standard break alerts
            lunch_advance = remaining_lunch <= lunch_advance_sec and remaining_lunch > self.lunch_final_sec
            lunch_final = remaining_lunch <= self.lunch_final_sec and break_duration < (self.lunch_target_seconds + 300)

            # Extended break alerts approaching 2h limit (CLT Art. 71 / gym / errands)
            max_lunch_seconds = 7200  # 2 hours
            remaining_lunch_2h = max(0, max_lunch_seconds - break_duration)
            lunch_2h_advance = (
                remaining_lunch_2h <= lunch_advance_sec
                and remaining_lunch_2h > self.lunch_final_sec
                and break_duration > self.lunch_target_seconds
            )
            lunch_2h_final = (
                remaining_lunch_2h <= self.lunch_final_sec
                and break_duration > self.lunch_target_seconds
            )

            return EmployeeWorkdayStatus(
                employee_id=employee_id,
                stage=WorkdayStage.LUNCH_BREAK,
                worked_seconds=total_worked,
                continuous_worked_seconds=0,
                lunch_duration_seconds=break_duration,
                remaining_lunch_seconds=remaining_lunch,
                remaining_lunch_2h_seconds=remaining_lunch_2h,
                remaining_work_seconds=remaining_work,
                estimated_end_time=None,
                times=clean_times,
                lunch_advance_alert=lunch_advance,
                lunch_final_alert=lunch_final,
                lunch_2h_advance_alert=lunch_2h_advance,
                lunch_2h_final_alert=lunch_2h_final,
            )
