from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import models  # noqa: F401
from app.api import router, seed_rbac
from app.config import get_settings
from app.database import SessionLocal
from app.device_api import ensure_device_monitoring, router as device_router
from app.emqx import EMQXError, get_emqx
from app.models import Device

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    with SessionLocal() as db:
        seed_rbac(db)
        devices = db.scalars(select(Device).options(selectinload(Device.topics))).all()
        device_rules = [
            (device.client_id, [
                {"topic": topic.topic, "action": topic.action, "permission": "allow", "qos": topic.qos, "retain": topic.retain}
                for topic in device.topics
            ])
            for device in devices
        ]
    if device_rules:
        try:
            broker = get_emqx()
            broker.ensure_access_control()
            ensure_device_monitoring()
            for client_id, rules in device_rules:
                broker.set_device_rules(client_id, rules)
                broker.disconnect_client(client_id)
        except EMQXError:
            logger.exception("Could not synchronize device MQTT ACLs during startup")
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
app.include_router(device_router)


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "service": settings.app_name}


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
