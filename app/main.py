"""Splunky Finance lab portal: the guide, registration, and the instructor's admin page."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import store
from .config import ROOT, settings
from .routes import admin, api, public
from .worker import creator


@asynccontextmanager
async def lifespan(app):
    store.init_db()
    creator.start()
    try:
        yield
    finally:
        creator.stop()


app = FastAPI(title="Splunky Finance lab portal", docs_url=None, redoc_url=None,
              openapi_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")
app.include_router(public.router)
app.include_router(api.router)
app.include_router(admin.router)


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True, "dry_run": settings.dry_run, "armed": creator.armed}


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """Browsers ask for /favicon.ico whatever the page declares, and remember the answer."""
    return FileResponse(ROOT / "app" / "static" / "favicon.ico", media_type="image/x-icon")
