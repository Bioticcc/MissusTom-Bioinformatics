from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from missus_tom.api.routes import router, run_manager
from missus_tom.config import settings
from missus_tom.logging_config import configure_logging
from missus_tom.models.common import ApiResponse, ErrorDetail

configure_logging()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    run_manager.shutdown()


app = FastAPI(
    title="Missus Tom local API",
    version=settings.app_version,
    description="Local-only project validation and controlled workflow API.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "tauri://localhost",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.include_router(router)


def _error_response(status_code: int, errors: list[ErrorDetail]) -> JSONResponse:
    envelope: ApiResponse[dict[str, Any]] = ApiResponse(success=False, errors=errors)
    return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return _error_response(
        exc.status_code,
        [ErrorDetail(code=f"http_{exc.status_code}", message=str(exc.detail))],
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for error in exc.errors():
        grouped.setdefault(error["msg"], []).append(error)
    errors: list[ErrorDetail] = []
    for message, matching in grouped.items():
        first = matching[0]
        count = len(matching)
        errors.append(
            ErrorDetail(
                code="validation_error",
                message=f"{message} ({count} fields)" if count > 1 else message,
                field=".".join(str(part) for part in first["loc"]),
                context={"type": first["type"], "field_count": count},
            )
        )
    return _error_response(422, errors)


def run() -> None:
    uvicorn.run("missus_tom.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    run()
