from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException


class FieldError(BaseModel):
    field: str
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[FieldError] | None = None


class ErrorResponse(BaseModel):
    """The one error shape every endpoint returns: {"error": {"code": ..., "message": ...}}."""

    error: ErrorBody


class ApiError(Exception):
    """Raise this from a route to answer with the envelope and a stable code."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _envelope(status_code: int, body: ErrorBody) -> JSONResponse:
    content = ErrorResponse(error=body).model_dump(exclude_none=True)
    return JSONResponse(status_code=status_code, content=content)


def _field(error: dict[str, Any]) -> str:
    loc: tuple[Any, ...] = error["loc"]
    # Unparseable JSON has loc ("body", <character position>); the whole body is at fault
    if error["type"] == "json_invalid" or len(loc) == 1:
        return str(loc[0])
    # ("body", "email") -> "email", ("query", "limit") -> "limit", ("body", "items", 0) -> "items.0"
    return ".".join(str(part) for part in loc[1:])


async def _api_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return _envelope(exc.status_code, ErrorBody(code=exc.code, message=exc.message))


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # Built from loc and msg only. FastAPI's default 422 also echoes "input", the password included.
    details = [FieldError(field=_field(err), message=err["msg"]) for err in exc.errors()]
    body = ErrorBody(code="VALIDATION_ERROR", message="The request is not valid.", details=details)
    return _envelope(422, body)


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    # 404 -> NOT_FOUND, 405 -> METHOD_NOT_ALLOWED, ...
    code = HTTPStatus(exc.status_code).name
    message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    response = _envelope(exc.status_code, ErrorBody(code=code, message=message))
    if exc.headers:
        response.headers.update(exc.headers)
    return response


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
