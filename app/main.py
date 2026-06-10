from __future__ import annotations

from fastapi import FastAPI
from fastmcp.utilities.lifespan import combine_lifespans

from app.core.config import get_settings
from app.db import models  # noqa: F401
from app.routers.documents import router as documents_router
from app.routers.health import router as health_router
from app.mcp.server import mcp_app

settings = get_settings()

app = FastAPI(title=settings.app_name, lifespan=combine_lifespans(mcp_app.lifespan))
app.mount("/mcp", mcp_app)
app.include_router(health_router)
app.include_router(documents_router)


@app.get("/")
def root() -> dict[str, str]:
    return {"service": settings.app_name, "status": "ready"}
