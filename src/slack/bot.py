"""Slack Bot client for sending direct messages to company employees."""

import logging
from typing import Any, Optional
import httpx

from .blocks import build_workday_notification_blocks
from ..database.db import AdminDatabase

logger = logging.getLogger(__name__)


class SlackBot:
    """Dispatches direct messages to employees via Slack Web API."""

    def __init__(self, bot_token: Optional[str], db: AdminDatabase, enabled: bool = True):
        self.bot_token = bot_token.strip() if bot_token else None
        self.db = db
        self.enabled = enabled and bool(self.bot_token and self.bot_token.startswith("xoxb-"))

        self._client = httpx.AsyncClient(
            base_url="https://slack.com/api",
            headers={
                "Authorization": f"Bearer {self.bot_token}" if self.bot_token else "",
                "Content-Type": "application/json; charset=utf-8",
            },
            timeout=15.0,
        )

    async def lookup_user_by_email(self, email: str) -> Optional[str]:
        """Lookup Slack user ID by email address."""
        if not self.enabled or not email:
            return None

        try:
            resp = await self._client.get("/users.lookupByEmail", params={"email": email.strip()})
            data = resp.json()
            if data.get("ok"):
                user_id = data["user"]["id"]
                logger.info("Matched Slack user %s for email %s", user_id, email)
                return user_id
            else:
                logger.warning("Slack user lookup failed for %s: %s", email, data.get("error"))
                return None
        except Exception as e:
            logger.exception("Error looking up Slack user by email %s: %s", email, e)
            return None

    async def lookup_user_by_name(self, full_name: str) -> Optional[str]:
        """Lookup Slack user ID by full name from users.list (requires users:read)."""
        if not self.enabled or not full_name:
            return None
        try:
            resp = await self._client.get("/users.list")
            data = resp.json()
            if not data.get("ok"):
                return None
            target = full_name.strip().lower()
            for m in data.get("members", []):
                if m.get("is_bot") or m.get("id") == "USLACKBOT":
                    continue
                real_name = (m.get("real_name") or "").lower()
                profile_name = (m.get("profile", {}).get("real_name") or "").lower()
                user_name = (m.get("name") or "").lower()
                if (target and (target in real_name or target in profile_name or real_name in target)) or (user_name and user_name in target):
                    logger.info("Matched Slack user %s for name %s", m["id"], full_name)
                    return m["id"]
            return None
        except Exception as e:
            logger.exception("Error searching Slack user by name %s: %s", full_name, e)
            return None

    async def open_dm_channel(self, slack_user_id: str) -> Optional[str]:
        """Open a Direct Message channel with the user."""
        if not self.enabled:
            return None
        try:
            resp = await self._client.post("/conversations.open", json={"users": slack_user_id})
            data = resp.json()
            if data.get("ok"):
                return data["channel"]["id"]
            logger.warning("Failed to open DM channel with %s: %s", slack_user_id, data.get("error"))
            return None
        except Exception as e:
            logger.exception("Error opening DM channel: %s", e)
            return None

    async def send_dm_to_employee(
        self,
        employee_id: str,
        email: str,
        title: str,
        message: str,
        stage_text: str,
        level: str = "info",
        allow_customization: bool = True,
        advance_minutes: int = 10,
    ) -> bool:
        """Send direct message to an employee, resolving email to Slack user ID."""
        if not self.enabled:
            logger.info("Slack Bot disabled. Skipping DM to employee %s", employee_id)
            return False

        emp = self.db.get_employee(employee_id)
        slack_user_id = emp.get("slack_user_id") if emp else None

        # Resolve if not cached
        if not slack_user_id:
            slack_user_id = await self.lookup_user_by_email(email)
            if not slack_user_id and emp and emp.get("full_name"):
                slack_user_id = await self.lookup_user_by_name(emp["full_name"])
            if slack_user_id:
                self.db.update_employee_slack_id(employee_id, slack_user_id)

        if not slack_user_id:
            logger.warning("Cannot send Slack notification: no Slack user found for %s (%s)", employee_id, email)
            return False

        channel_id = await self.open_dm_channel(slack_user_id)
        if not channel_id:
            return False

        blocks = build_workday_notification_blocks(
            title=title,
            message=message,
            stage_text=stage_text,
            level=level,
            allow_customization=allow_customization,
            current_advance_minutes=advance_minutes,
        )

        payload = {
            "channel": channel_id,
            "text": f"{title} — {message}",
            "blocks": blocks,
        }

        try:
            resp = await self._client.post("/chat.postMessage", json=payload)
            data = resp.json()
            if data.get("ok"):
                logger.info("Sent Slack DM to employee %s in channel %s", employee_id, channel_id)
                return True
            else:
                logger.error("Failed to post message to Slack channel %s: %s", channel_id, data.get("error"))
                return False
        except Exception as e:
            logger.exception("Error posting Slack DM: %s", e)
            return False

    async def close(self):
        await self._client.aclose()
