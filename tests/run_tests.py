"""Test suite runner for TiqueTaque Sync Admin."""

import unittest
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_database import TestAdminDatabase
from tests.test_workday import TestWorkdayEngine
from tests.test_slack_bot import TestSlackBot
from tests.test_security import TestSecurity
from tests.test_alert_storms import TestRajadasDeAlerta

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestAdminDatabase))
    suite.addTests(loader.loadTestsFromTestCase(TestWorkdayEngine))
    suite.addTests(loader.loadTestsFromTestCase(TestSlackBot))
    suite.addTests(loader.loadTestsFromTestCase(TestSecurity))
    suite.addTests(loader.loadTestsFromTestCase(TestRajadasDeAlerta))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if not result.wasSuccessful():
        sys.exit(1)
