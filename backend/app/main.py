import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .config import get_settings
from .routers import admin, allocation, auth, faculty, notifications, public, reports, team

log = logging.getLogger("app")
settings = get_settings()

app = FastAPI(title="Project Guide Allocation API", version="2.0.0",
              description="Team-based project guide allocation (MySQL, rule-based, no AI).")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

API = "/api/v1"
for r in (public.router, auth.router, team.router, faculty.router, notifications.router, admin.router,
          allocation.router, reports.router):
    app.include_router(r, prefix=API)


def _field_errors(exc: RequestValidationError):
    out = []
    for e in exc.errors():
        loc = [str(p) for p in e["loc"] if p not in ("body", "query", "path")]
        out.append({"field": ".".join(loc), "message": e["msg"].replace("Value error, ", "")})
    return out


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    errs = _field_errors(exc)
    msg = "; ".join(f"{e['field']}: {e['message']}" if e["field"] else e["message"] for e in errs[:3])
    return JSONResponse(status_code=422, content={"detail": {"code": "validation_error", "message": msg or "Invalid input.",
                                                              "errors": errs}})


@app.exception_handler(SQLAlchemyError)
async def db_handler(request: Request, exc: SQLAlchemyError):
    log.exception("Database error on %s %s", request.method, request.url.path)  # details stay in the server log
    if isinstance(exc, DBAPIError) and exc.connection_invalidated:
        return JSONResponse(status_code=503, content={"detail": "The database is temporarily unavailable. Try again shortly."})
    return JSONResponse(status_code=500, content={"detail": "A database error occurred. The request was not completed."})


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "An unexpected error occurred."})


@app.get("/health")
def health():
    return {"status": "ok"}
