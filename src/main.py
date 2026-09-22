"""Main FastAPI application for TiqueTaque Sync Admin."""

import json
import logging
import urllib.parse
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
import pytz

from fastapi import FastAPI, HTTPException, Request, Response, APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .config import settings
from .tiquetaque.client import TiqueTaqueAdminClient
from .database.db import AdminDatabase
from .engine.workday import WorkdayEngine
from .engine.scheduler import AdminSyncScheduler
from .slack.bot import SlackBot
from .slack.interactions import handle_slack_interaction
from .slack.security import verify_slack_signature, verify_slack_team
from .security import verify_admin_access, generate_admin_session_token

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("tiquetaque_sync_admin")

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "web" / "templates"
STATIC_DIR = BASE_DIR / "web" / "static"

# Shared Context
_db = AdminDatabase(settings.db_path)
_tt_client = TiqueTaqueAdminClient(token=settings.tiquetaque_admin_token, base_url=settings.tiquetaque_api_base_url)
_slack_bot = SlackBot(bot_token=settings.slack_bot_token, db=_db, enabled=settings.slack_enabled)
_engine = WorkdayEngine(
    target_hours=settings.default_work_hours_per_day,
    lunch_duration_minutes=settings.default_lunch_duration_minutes,
    continuous_work_limit_hours=settings.default_continuous_work_limit_hours,
    lunch_warning_final_minutes=settings.default_lunch_warning_final_minutes,
    end_work_warning_final_minutes=settings.default_end_work_warning_final_minutes,
    continuous_work_warning_final_minutes=settings.default_continuous_work_warning_final_minutes,
    timezone_name=settings.timezone,
)
_scheduler = AdminSyncScheduler(
    client=_tt_client,
    engine=_engine,
    database=_db,
    bot=_slack_bot,
    poll_interval_seconds=settings.poll_interval_seconds,
    alert_ticker_interval_seconds=settings.alert_ticker_interval_seconds,
    timezone_name=settings.timezone,
)

app_context = {
    "db": _db,
    "client": _tt_client,
    "bot": _slack_bot,
    "engine": _engine,
    "scheduler": _scheduler,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup and shutdown routines."""
    logger.info("Initializing TiqueTaque Sync Admin Service...")
    scheduler: AdminSyncScheduler = app_context["scheduler"]
    client: TiqueTaqueAdminClient = app_context["client"]
    bot: SlackBot = app_context["bot"]

    # Start background polling and ticker
    await scheduler.start()

    yield

    logger.info("Shutting down TiqueTaque Sync Admin Service...")
    await scheduler.stop()
    await client.close()
    await bot.close()


app = FastAPI(
    title="TiqueTaque Sync Admin",
    description="Enterprise Employee Workday Notifications & Interactive Slack Bot for TiqueTaque",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ------------------------------------------------------------------------------
# Dashboard Route
# ------------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def serve_admin_dashboard(request: Request):
    """Serve the enterprise administration dashboard with signed session token."""
    token = generate_admin_session_token()
    response = templates.TemplateResponse(request=request, name="index.html", context={"admin_token": token})
    response.set_cookie(key="admin_session", value=token, httponly=True, samesite="lax")
    return response


# ------------------------------------------------------------------------------
# Admin API Endpoints (Protected by verify_admin_access)
# ------------------------------------------------------------------------------
admin_router = APIRouter(prefix="/api/admin", dependencies=[Depends(verify_admin_access)])


@admin_router.get("/metrics")
async def get_metrics():
    """Return top-level counts and status."""
    db: AdminDatabase = app_context["db"]
    bot: SlackBot = app_context["bot"]
    scheduler: AdminSyncScheduler = app_context["scheduler"]

    emps = db.get_all_employees()
    total = len(emps)
    active = sum(1 for e in emps if e.get("notifications_enabled"))

    synced_today = 0
    for e in emps:
        punches = scheduler._cached_punches.get(e["id"], [])
        if punches:
            synced_today += 1

    return {
        "total_employees": total,
        "active_notifications": active,
        "synced_today": synced_today,
        "slack_connected": bot.enabled,
    }


@admin_router.get("/employees")
async def list_employees():
    """Return all employees with their punches and current stage."""
    db: AdminDatabase = app_context["db"]
    scheduler: AdminSyncScheduler = app_context["scheduler"]
    emps = db.get_all_employees()

    result = []
    for e in emps:
        emp_id = e["id"]
        status = scheduler.get_status_for_employee(emp_id)
        punches = scheduler._cached_punches.get(emp_id, [])

        result.append({
            "id": emp_id,
            "full_name": e["full_name"],
            "email": e.get("email"),
            "notifications_enabled": bool(e.get("notifications_enabled")),
            "lunch_warning_advance_minutes": e.get("lunch_warning_advance_minutes") or 10,
            "end_work_warning_advance_minutes": e.get("end_work_warning_advance_minutes") or 15,
            "continuous_work_warning_advance_minutes": e.get("continuous_work_warning_advance_minutes") or 10,
            "today_punches": punches,
            "current_stage": status.stage.value if status else "not_started",
            "worked_hours_str": status.worked_hours_str if status else "00h00m",
            "estimated_end_time": status.estimated_end_time if status else None,
        })
    return result


class ToggleRequest(BaseModel):
    enabled: bool


@admin_router.post("/employees/{employee_id}/toggle")
async def toggle_employee_notifications(employee_id: str, payload: ToggleRequest):
    """Enable or disable notifications for a specific employee."""
    db: AdminDatabase = app_context["db"]
    db.update_employee_toggle(employee_id, payload.enabled)
    return {"success": True, "employee_id": employee_id, "notifications_enabled": payload.enabled}


class PreferencesRequest(BaseModel):
    advance_minutes: int


@admin_router.post("/employees/{employee_id}/preferences")
async def update_employee_preferences(employee_id: str, payload: PreferencesRequest):
    """Update advance warning lead time for an employee."""
    db: AdminDatabase = app_context["db"]
    db.update_employee_preferences(
        employee_id=employee_id,
        lunch_minutes=payload.advance_minutes,
        end_work_minutes=payload.advance_minutes,
        clt_minutes=payload.advance_minutes,
    )
    return {"success": True, "employee_id": employee_id, "advance_minutes": payload.advance_minutes}


@admin_router.post("/employees/{employee_id}/test-slack")
async def test_slack_for_employee(employee_id: str):
    """Send a test notification DM to an employee via Slack."""
    db: AdminDatabase = app_context["db"]
    bot: SlackBot = app_context["bot"]
    emp = db.get_employee(employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Colaborador não encontrado")

    if not bot.enabled:
        raise HTTPException(status_code=400, detail="Slack Bot não está habilitado ou token é inválido")

    allow_custom = db.get_company_setting("allow_employee_customization", "true") == "true"
    lead_time = emp.get("lunch_warning_advance_minutes") or 10

    success = await bot.send_dm_to_employee(
        employee_id=employee_id,
        email=emp.get("email"),
        title="Mensagem de Verificação — TiqueTaque Ponto",
        message=(
            f"Olá *{emp['full_name']}*! Este é um teste do assistente de ponto da sua empresa. "
            f"Você receberá alertas automáticos de almoço, término de jornada e intervalos CLT diretamente por aqui! 🚀"
        ),
        stage_text="Verificação",
        level="success",
        allow_customization=allow_custom,
        advance_minutes=lead_time,
    )
    return {"success": success}


class SimulatePunchesPayload(BaseModel):
    remaining_minutes: int = 8
    punches: list[str] | None = None


@admin_router.post("/employees/{employee_id}/simulate-workday")
async def simulate_workday_for_employee(employee_id: str, payload: SimulatePunchesPayload = SimulatePunchesPayload()):
    """Simulate/override employee punches for today to trigger alert testing."""
    db: AdminDatabase = app_context["db"]
    scheduler: AdminSyncScheduler = app_context["scheduler"]
    emp = db.get_employee(employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Colaborador não encontrado")

    now = datetime.now(scheduler.tz)
    today_date_str = now.strftime("%d/%m/%Y")

    if payload.punches:
        simulated_punches = payload.punches
    else:
        # Generate 3 punches so remaining_work is exactly remaining_minutes
        # Morning: 14:00 - 18:00 (4h worked)
        # Afternoon target: 4h
        # End time: now + remaining_minutes
        # Afternoon start = (now + remaining_minutes) - 4 hours
        rem_min = payload.remaining_minutes
        afternoon_start_dt = now + timedelta(minutes=rem_min) - timedelta(hours=4)
        simulated_punches = ["14:00", "18:00", afternoon_start_dt.strftime("%H:%M")]

    # Clear previously dispatched alerts for today so it fires fresh
    db.clear_dispatched_alert(employee_id, today_date_str, "end_work_advance")

    # Store in override and cache
    scheduler._punches_override[employee_id] = simulated_punches
    scheduler._cached_punches[employee_id] = simulated_punches

    # Re-evaluate alerts immediately to dispatch Slack DM
    await scheduler._evaluate_and_dispatch_alerts()

    status = scheduler._cached_status.get(employee_id)
    return {
        "success": True,
        "employee_id": employee_id,
        "simulated_punches": simulated_punches,
        "estimated_end_time": status.estimated_end_time if status else None,
        "remaining_work_seconds": status.remaining_work_seconds if status else None,
        "end_work_advance_alert": status.end_work_advance_alert if status else None,
    }


@admin_router.post("/employees/{employee_id}/reset-punches")
async def reset_punches_for_employee(employee_id: str):
    """Reset simulated punches back to real TiqueTaque API data."""
    scheduler: AdminSyncScheduler = app_context["scheduler"]
    scheduler._punches_override.pop(employee_id, None)
    await scheduler.sync_company()
    return {"success": True, "message": "Punches reset to real TiqueTaque data"}


@admin_router.post("/sync")
async def trigger_company_sync():
    """Trigger immediate company-wide sync with TiqueTaque Public Admin API."""
    scheduler: AdminSyncScheduler = app_context["scheduler"]
    try:
        await scheduler.sync_company()
        return {"success": True, "message": "Company sync executed successfully"}
    except Exception as e:
        logger.exception("Manual sync failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@admin_router.get("/policy")
async def get_company_policy():
    """Return company policy configuration."""
    db: AdminDatabase = app_context["db"]
    allow_custom = db.get_company_setting("allow_employee_customization", "true") == "true"
    lead_time = int(db.get_company_setting("default_lead_time", str(settings.default_lunch_warning_advance_minutes)))

    return {
        "allow_employee_customization": allow_custom,
        "default_lead_time": lead_time,
        "default_lunch_advance": lead_time,
        "default_end_advance": lead_time,
        "default_clt_advance": lead_time,
    }


class PolicyRequest(BaseModel):
    allow_employee_customization: bool
    default_lead_time: int = 10
    default_lunch_advance: int | None = None
    default_end_advance: int | None = None
    default_clt_advance: int | None = None


@admin_router.post("/policy")
async def save_company_policy(payload: PolicyRequest):
    """Save company policy configuration."""
    db: AdminDatabase = app_context["db"]
    val = payload.default_lead_time or payload.default_lunch_advance or 10
    db.set_company_setting("allow_employee_customization", "true" if payload.allow_employee_customization else "false")
    db.set_company_setting("default_lead_time", str(val))
    db.set_company_setting("default_lunch_advance", str(val))
    db.set_company_setting("default_end_advance", str(val))
    db.set_company_setting("default_clt_advance", str(val))
    return {"success": True, "allow_employee_customization": payload.allow_employee_customization, "default_lead_time": val}


@admin_router.get("/backup/export")
async def export_backup():
    """Download database preferences as a portable JSON file."""
    db: AdminDatabase = app_context["db"]
    backup_data = db.export_config_backup()
    filename = f"tique-taque-admin-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"

    return Response(
        content=json.dumps(backup_data, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@admin_router.post("/backup/import")
async def import_backup(payload: dict[str, Any]):
    """Restore database preferences from a JSON backup."""
    db: AdminDatabase = app_context["db"]
    try:
        result = db.import_config_backup(payload)
        return {"success": True, **result}
    except Exception as e:
        logger.exception("Backup import error: %s", e)
        raise HTTPException(status_code=400, detail=f"Erro ao importar backup: {e}")


# Register Protected Admin Router
app.include_router(admin_router)


# ------------------------------------------------------------------------------
# Slack Interactive Webhook
# ------------------------------------------------------------------------------
@app.post("/api/slack/interactions")
async def receive_slack_interaction(request: Request):
    """Endpoint receiving button clicks from Slack Block Kit messages."""
    body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp")
    signature = request.headers.get("X-Slack-Signature")

    # 1. Cryptographic HMAC-SHA256 signature verification
    if not verify_slack_signature(
        signing_secret=settings.slack_signing_secret,
        timestamp=timestamp,
        signature=signature,
        body=body,
    ):
        logger.warning("Rejected Slack interaction: invalid signature")
        raise HTTPException(status_code=403, detail="Invalid Slack signature")

    # 2. Parse form payload
    form_data = urllib.parse.parse_qs(body.decode("utf-8"))
    payload_raw_list = form_data.get("payload")
    if not payload_raw_list or not payload_raw_list[0]:
        raise HTTPException(status_code=400, detail="Missing payload parameter")

    try:
        payload = json.loads(payload_raw_list[0])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON in payload")

    # 3. Workspace/organization verification
    if not verify_slack_team(payload, settings.slack_allowed_team_id):
        raise HTTPException(status_code=403, detail="Unauthorized Slack workspace")

    db: AdminDatabase = app_context["db"]
    response = handle_slack_interaction(payload, db)
    return JSONResponse(content=response)


# ------------------------------------------------------------------------------
# Health Probe
# ------------------------------------------------------------------------------
@app.get("/healthz")
async def health_check():
    """Liveness/readiness probe for Kubernetes."""
    return {"status": "ok", "service": "tique-taque-sync-admin", "timestamp": datetime.now(pytz.utc).isoformat()}
