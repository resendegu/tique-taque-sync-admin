"""Security utilities for validating incoming Slack webhook requests."""

import hashlib
import hmac
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


def verify_slack_signature(
    signing_secret: Optional[str],
    timestamp: Optional[str],
    signature: Optional[str],
    body: bytes,
    max_age_seconds: int = 300,
) -> bool:
    """
    Verify incoming request from Slack using HMAC-SHA256 signing secret.
    
    Reference: https://api.slack.com/authentication/verifying-requests-from-slack
    """
    if not signing_secret:
        logger.warning("SLACK_SIGNING_SECRET not configured; skipping signature check")
        return True

    if not timestamp or not signature:
        logger.warning("Missing Slack signature headers (timestamp=%s, signature=%s)", bool(timestamp), bool(signature))
        return False

    # Prevent replay attacks: ensure timestamp is within tolerance (default 5 minutes)
    try:
        req_time = int(timestamp)
        now = int(time.time())
        if abs(now - req_time) > max_age_seconds:
            logger.warning("Slack request timestamp expired: now=%d, req_time=%d", now, req_time)
            return False
    except ValueError:
        logger.warning("Invalid Slack timestamp format: %s", timestamp)
        return False

    # Compute expected signature: v0=HMAC_SHA256(secret, "v0:" + timestamp + ":" + body)
    sig_basestring = f"v0:{timestamp}:".encode("utf-8") + body
    expected_signature = (
        "v0="
        + hmac.new(
            signing_secret.encode("utf-8"),
            sig_basestring,
            hashlib.sha256,
        ).hexdigest()
    )

    is_valid = hmac.compare_digest(expected_signature, signature)
    if not is_valid:
        logger.warning("Slack signature mismatch! Provided=%s, Expected=%s", signature, expected_signature)
    return is_valid


def verify_slack_team(payload: dict, allowed_team_id: Optional[str]) -> bool:
    """
    Verify that the interaction payload comes from the designated Slack team/workspace.
    """
    if not allowed_team_id:
        return True

    team_id = payload.get("team", {}).get("id") or payload.get("user", {}).get("team_id")
    if not team_id:
        logger.warning("No team ID found in Slack interaction payload")
        return False

    if team_id.strip() != allowed_team_id.strip():
        logger.warning(
            "Rejected Slack interaction from unauthorized team %s (expected %s)",
            team_id,
            allowed_team_id,
        )
        return False

    return True
