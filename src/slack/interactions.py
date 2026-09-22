"""Interactive action handler for Slack Block Kit events."""

import logging
from typing import Any
from ..database.db import AdminDatabase

logger = logging.getLogger(__name__)


def handle_slack_interaction(payload: dict[str, Any], db: AdminDatabase) -> dict[str, Any]:
    """Process button clicks from 'TiqueTaque Ponto' messages.

    Handles actions like:
      - set_lead_time_5
      - set_lead_time_10
      - set_lead_time_15
      - mute_alerts
    """
    user_info = payload.get("user", {})
    slack_user_id = user_info.get("id")
    actions = payload.get("actions", [])

    if not actions:
        return {"response_action": "clear"}

    action = actions[0]
    action_id = action.get("action_id", "")
    value = action.get("value", "")

    logger.info("Processing Slack interaction from user %s: action_id=%s, value=%s", slack_user_id, action_id, value)

    # Find employee by slack_user_id
    all_emps = db.get_all_employees()
    emp = next((e for e in all_emps if e.get("slack_user_id") == slack_user_id), None)

    if not emp:
        return {
            "replace_original": False,
            "text": "⚠️ Colaborador não encontrado no sistema TiqueTaque Sync.",
        }

    employee_id = emp["id"]

    # Check company policy: if customization is disabled, reject changes
    allow_customization = db.get_company_setting("allow_employee_customization", "true") == "true"
    if not allow_customization:
        logger.info("Rejected Slack interaction: employee customization is disabled by company policy")
        return {
            "replace_original": False,
            "text": "🔒 *A customização e o silenciamento de alertas foram desativados pelas diretrizes da sua empresa.* Suas notificações seguem os parâmetros definidos pelo RH.",
        }

    if action_id == "mute_alerts":
        db.update_employee_toggle(employee_id, False)
        return {
            "replace_original": False,
            "text": f"🔕 *Notificações silenciadas com sucesso!* Você não receberá mais alertas automáticos do TiqueTaque Ponto. Para reativar, contate o administrador de RH ou o gestor da sua empresa.",
        }

    if action_id.startswith("set_lead_time_"):
        try:
            mins = int(value)
            db.update_employee_preferences(
                employee_id=employee_id,
                lunch_minutes=mins,
                end_work_minutes=mins,
                clt_minutes=mins,
            )
            return {
                "replace_original": False,
                "text": f"✅ *Preferência atualizada!* A partir de agora você será avisado com *{mins} minutos de antecedência* antes do término do almoço e do expediente.",
            }
        except ValueError:
            pass

    return {"response_action": "clear"}
