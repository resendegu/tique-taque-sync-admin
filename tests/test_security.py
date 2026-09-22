"""Unit tests for Slack webhook signature verification and admin access control."""

import hashlib
import hmac
import time
import unittest
from unittest.mock import MagicMock

from src.slack.security import verify_slack_signature, verify_slack_team
from src.security import generate_admin_session_token, verify_admin_session_token, verify_admin_access
from src.config import settings


class TestSecurity(unittest.TestCase):
    def test_slack_signature_valid(self):
        secret = "test_signing_secret_123"
        now = str(int(time.time()))
        body = b"payload=%7B%22type%22%3A%22block_actions%22%7D"

        sig_basestring = f"v0:{now}:".encode("utf-8") + body
        sig = "v0=" + hmac.new(secret.encode("utf-8"), sig_basestring, hashlib.sha256).hexdigest()

        self.assertTrue(verify_slack_signature(secret, now, sig, body))

    def test_slack_signature_invalid(self):
        secret = "test_signing_secret_123"
        now = str(int(time.time()))
        body = b"payload=%7B%22type%22%3A%22block_actions%22%7D"

        self.assertFalse(verify_slack_signature(secret, now, "v0=invalid_hash", body))

    def test_slack_signature_replay_attack(self):
        secret = "test_signing_secret_123"
        expired_ts = str(int(time.time()) - 600)  # 10 minutes ago
        body = b"test"
        sig = "v0=" + hmac.new(secret.encode("utf-8"), f"v0:{expired_ts}:test".encode("utf-8"), hashlib.sha256).hexdigest()

        self.assertFalse(verify_slack_signature(secret, expired_ts, sig, body))

    def test_slack_team_verification(self):
        payload = {"team": {"id": "T01V8LQHBE1"}}
        self.assertTrue(verify_slack_team(payload, "T01V8LQHBE1"))
        self.assertFalse(verify_slack_team(payload, "TOTHERTEAM"))
        self.assertTrue(verify_slack_team(payload, None))  # No restriction

    def test_admin_session_token_generation_and_verification(self):
        token = generate_admin_session_token()
        self.assertTrue(verify_admin_session_token(token))
        self.assertFalse(verify_admin_session_token("invalid.token"))
        self.assertFalse(verify_admin_session_token(""))


if __name__ == "__main__":
    unittest.main()
