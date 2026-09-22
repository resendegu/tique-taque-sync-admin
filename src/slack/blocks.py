"""Slack Block Kit message builders for 'TiqueTaque Ponto' bot."""

from typing import Any


def build_workday_notification_blocks(
    title: str,
    message: str,
    stage_text: str,
    level: str = "info",
    allow_customization: bool = True,
    current_advance_minutes: int = 10,
) -> list[dict[str, Any]]:
    """Build rich Slack Block Kit layout with optional interactive buttons."""
    icon = {
        "info": "ℹ️",
        "warning": "⚠️",
        "critical": "🚨",
        "success": "✅",
    }.get(level, "🕒")

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{icon} {title}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": message,
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"📊 *Status:* {stage_text}  •  🤖 *TiqueTaque Ponto*",
                }
            ],
        },
    ]

    # Add interactive settings buttons if company policy allows employee customization
    if allow_customization:
        def _btn(text: str, action_id: str, value: str, is_primary: bool = False, is_danger: bool = False) -> dict[str, Any]:
            b: dict[str, Any] = {
                "type": "button",
                "text": {"type": "plain_text", "text": text, "emoji": True},
                "action_id": action_id,
                "value": value,
            }
            if is_primary:
                b["style"] = "primary"
            elif is_danger:
                b["style"] = "danger"
            return b

        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"⚙️ *Preferência de Antecedência:* (Atual: `{current_advance_minutes} min`)\n"
                    "Com quantos minutos de antecedência você prefere ser avisado?"
                ),
            },
        })
        blocks.append({
            "type": "actions",
            "block_id": "tique_taque_ponto_preferences",
            "elements": [
                _btn("5 min", "set_lead_time_5", "5", is_primary=(current_advance_minutes == 5)),
                _btn("10 min", "set_lead_time_10", "10", is_primary=(current_advance_minutes == 10)),
                _btn("15 min", "set_lead_time_15", "15", is_primary=(current_advance_minutes == 15)),
                _btn("🔕 Silenciar", "mute_alerts", "mute", is_danger=True),
            ],
        })
    else:
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "🔒 _Avisos pré-configurados pela política da sua empresa._",
                }
            ],
        })

    return blocks
