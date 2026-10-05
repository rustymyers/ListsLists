from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.database import Base, SessionLocal, engine
from app.routers import admin, api, auth, web
from app.security import csrf_token
from app.services.bootstrap import bootstrap_admin

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.environment == "production" and settings.secret_key == "development-only-change-me":
        raise RuntimeError("LISTSLISTS_SECRET_KEY must be set in production")
    settings.ensure_directories()
    if settings.environment in {"development", "test"}:
        Base.metadata.create_all(engine)
    with SessionLocal() as db:
        bootstrap_admin(db, settings)
    yield


app = FastAPI(title="ListsLists", version="0.0.1", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, https_only=settings.session_https_only, same_site="lax")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

templates.env.globals["csrf_token"] = csrf_token
app.state.templates = templates
app.include_router(auth.router)
app.include_router(web.router)
app.include_router(admin.router)
app.include_router(api.router)


@app.get("/healthz", include_in_schema=False)
def healthz():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok"}
    except Exception:
        return JSONResponse({"status": "degraded", "database": "error"}, status_code=503)


@app.exception_handler(403)
async def forbidden(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": str(exc.detail)}, status_code=403)
    return templates.TemplateResponse(request, "error.html", {"status": 403, "message": str(exc.detail)}, status_code=403)
