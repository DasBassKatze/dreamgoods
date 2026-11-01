"""Приложение FastAPI: маршруты API + собранный фронтенд (frontend/ → dreamgoods/web/)."""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .. import __version__
from ..core import auth, storage
from ..services.billing import by_master
from ..core.logs import log
from .routers import budgets, workflow, account, admin, auth as auth_routes, frames, generation, imports, media, personas, presets, products, projects, settings, styles

WEB = Path(__file__).resolve().parent.parent / "web"
NO_BUILD = """<!doctype html><meta charset="utf-8"><title>DreamGoods</title><body style="font:15px system-ui;padding:40px">
<h2>Интерфейс не собран</h2><p>Нет папки <code>dreamgoods/web</code>. Соберите фронтенд: <code>Сборка интерфейса.bat</code>
(или <code>cd frontend && npm install && npm run build</code>). API работает: <a href="/api/docs">/api/docs</a></p>"""


def create_app() -> FastAPI:
    app = FastAPI(title="DreamGoods API", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json",
                  description="Массовая генерация карточек товаров с ИИ-контролем. Тот же API используют веб-кабинет и бот.")

    warned = set()

    @app.exception_handler(LookupError)
    async def _not_found(request: Request, exc):
        if isinstance(exc, storage.Missing) and "missing" not in warned:   # одна строка в журнал, без трассировок
            warned.add("missing")
            log.error("Картинки не найдены в хранилище (%s). Скопируйте папку data из старой версии и перезапустите.", exc)
        return JSONResponse({"error": str(exc)}, 404)

    @app.middleware("http")
    async def _auth(request: Request, call_next):
        """Все /api/* — только после входа (кроме входа и проверки здоровья)."""
        path = request.url.path
        request.state.user = None
        if path.startswith("/api/"):
            token = auth.token_of(request)
            u = await run_in_threadpool(auth.user_by_token, token) if token else None
            request.state.user = u
            by_master.set(bool(u and u.master))
            if u is None and not path.startswith(auth.PUBLIC) and not path.startswith(("/api/docs", "/api/openapi")):
                return JSONResponse({"error": "войдите на сайт", "auth": False}, 401)
        return await call_next(request)

    @app.exception_handler(PermissionError)
    async def _forbidden(request: Request, exc):
        return JSONResponse({"error": str(exc)}, getattr(exc, "status", 403))

    @app.exception_handler(ValueError)
    async def _bad(request: Request, exc):
        return JSONResponse({"error": str(exc), "no_funds": getattr(exc, "status", 400) == 402}, getattr(exc, "status", 400))

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError):
        parts = [f"{'.'.join(str(x) for x in e.get('loc', [])[1:]) or 'запрос'}: {e.get('msg')}" for e in exc.errors()]
        return JSONResponse({"error": "неверные данные — " + "; ".join(parts), "detail": exc.errors()}, 422)

    @app.exception_handler(Exception)
    async def _err(request: Request, exc):
        log.exception("Ошибка обработки %s %s", request.method, request.url.path)
        return JSONResponse({"error": "Внутренняя ошибка сервера. Подробности записаны в журнал."}, 500)

    for r in (budgets, workflow, auth_routes, account, admin, projects, settings, generation, frames, products, personas, presets, styles, imports, media):
        app.include_router(r.router)
    app.include_router(account.public)

    @app.get("/api/health", tags=["служебное"])
    def health():
        return {"ok": True, "version": __version__}

    if (WEB / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str = ""):
        if path.startswith("api/"):
            return JSONResponse({"error": "нет такого метода API"}, 404)
        f = WEB / path
        if path and f.is_file() and WEB in f.resolve().parents:
            return FileResponse(f)
        index = WEB / "index.html"
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-store"})
        return HTMLResponse(NO_BUILD)

    return app


app = create_app()

