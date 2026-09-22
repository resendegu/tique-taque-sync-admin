"""Tests for WorkdayEngine and CLT compliance."""

import unittest
from datetime import datetime
import pytz

from src.engine.workday import WorkdayEngine, WorkdayStage


class TestWorkdayEngine(unittest.TestCase):
    def setUp(self):
        self.engine = WorkdayEngine(target_hours=8.0, timezone_name="America/Sao_Paulo")
        self.tz = pytz.timezone("America/Sao_Paulo")
        self.base_date = self.tz.localize(datetime(2026, 9, 21, 0, 0))

    def test_not_started(self):
        now = self.tz.localize(datetime(2026, 9, 21, 7, 30))
        status = self.engine.calculate("emp1", [], current_dt=now)
        self.assertEqual(status.stage, WorkdayStage.NOT_STARTED)
        self.assertEqual(status.worked_seconds, 0)
        self.assertEqual(status.remaining_work_seconds, 8 * 3600)

    def test_first_half_and_clt_limit(self):
        # Clock in at 08:00
        # Check at 13:51 (5h51m continuous work -> less than 10m before 6h limit)
        now = self.tz.localize(datetime(2026, 9, 21, 13, 51))
        status = self.engine.calculate("emp1", ["08:00"], current_dt=now, clt_advance_minutes=10)
        self.assertEqual(status.stage, WorkdayStage.FIRST_HALF)
        self.assertTrue(status.clt_advance_alert)
        self.assertFalse(status.clt_final_alert)

        # Check at 13:59:15 (less than 1m before 6h limit)
        now_final = self.tz.localize(datetime(2026, 9, 21, 13, 59, 15))
        status_final = self.engine.calculate("emp1", ["08:00"], current_dt=now_final, clt_advance_minutes=10)
        self.assertTrue(status_final.clt_final_alert)

    def test_lunch_break_and_alerts(self):
        # Punches: 08:00 (in), 12:00 (out to lunch)
        # Check at 12:51 (51 min in lunch -> 9 min remaining -> advance warning triggered)
        now_adv = self.tz.localize(datetime(2026, 9, 21, 12, 51))
        status = self.engine.calculate("emp1", ["08:00", "12:00"], current_dt=now_adv, lunch_advance_minutes=10)
        self.assertEqual(status.stage, WorkdayStage.LUNCH_BREAK)
        self.assertTrue(status.lunch_advance_alert)
        self.assertFalse(status.lunch_final_alert)

        # Check at 12:59:10 (less than 1m remaining)
        now_final = self.tz.localize(datetime(2026, 9, 21, 12, 59, 10))
        status_final = self.engine.calculate("emp1", ["08:00", "12:00"], current_dt=now_final, lunch_advance_minutes=10)
        self.assertTrue(status_final.lunch_final_alert)

    def test_second_half_prediction_and_completion(self):
        # 08:00, 12:00 (4h worked), 13:00 (afternoon start). Needs 4 more hours -> ends at 17:00
        now = self.tz.localize(datetime(2026, 9, 21, 16, 46)) # 14m remaining -> within 15m advance
        status = self.engine.calculate("emp1", ["08:00", "12:00", "13:00"], current_dt=now, end_work_advance_minutes=15)
        self.assertEqual(status.stage, WorkdayStage.SECOND_HALF)
        self.assertEqual(status.estimated_end_time, "17:00")
        self.assertTrue(status.end_work_advance_alert)
        self.assertFalse(status.end_work_final_alert)

        # 4 punches: completed
        status_comp = self.engine.calculate("emp1", ["08:00", "12:00", "13:00", "17:00"], current_dt=now)
        self.assertEqual(status_comp.stage, WorkdayStage.COMPLETED)
        self.assertEqual(status_comp.worked_hours_str, "08h00m")
        self.assertTrue(status_comp.summary_alert)


if __name__ == "__main__":
    unittest.main()
