"""Small versioned JSON-lines contract between Network Manager and providers.

The wire format is intentionally boring so providers can implement it without
depending on Network Manager internals.  This module validates the boundary;
it is not a transport daemon and never carries private credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Mapping


PROTOCOL_VERSION = 1
OPERATIONS = frozenset(
    {"status", "capabilities", "local-identities", "local-endpoints", "health", "apply-peers"}
)
_SECRET_WORDS = ("secret", "token", "password", "privatekey", "private_key", "credential")


class ProtocolError(ValueError):
    """A malformed or unsafe provider message."""


def _check_safe(value: Any, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).replace("-", "_").lower()
            if any(word in normalized for word in _SECRET_WORDS):
                raise ProtocolError(f"{path}.{key}: credential-bearing fields are not allowed")
            _check_safe(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _check_safe(child, f"{path}[{index}]")
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise ProtocolError(f"{path}: value is not JSON-compatible")


@dataclass(frozen=True)
class Request:
    request_id: str
    operation: str
    payload: Mapping[str, Any]
    version: int = PROTOCOL_VERSION

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Request":
        if not isinstance(value, Mapping):
            raise ProtocolError("request must be an object")
        version = value.get("version", PROTOCOL_VERSION)
        if version != PROTOCOL_VERSION:
            raise ProtocolError(f"unsupported protocol version: {version!r}")
        request_id = value.get("id")
        operation = value.get("operation")
        payload = value.get("payload", {})
        if not isinstance(request_id, str) or not request_id:
            raise ProtocolError("id must be a non-empty string")
        if not isinstance(operation, str) or not operation:
            raise ProtocolError("operation must be a non-empty string")
        if operation not in OPERATIONS:
            raise ProtocolError(f"unsupported operation: {operation}")
        if not isinstance(payload, Mapping):
            raise ProtocolError("payload must be an object")
        _check_safe(payload)
        return cls(request_id, operation, dict(payload), version)

    def to_mapping(self) -> dict[str, Any]:
        return {"version": self.version, "id": self.request_id, "operation": self.operation, "payload": dict(self.payload)}

    def to_json(self) -> str:
        return json.dumps(self.to_mapping(), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class Response:
    request_id: str
    ok: bool
    result: Mapping[str, Any] = field(default_factory=dict)
    error: str | None = None
    version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if self.ok and self.error is not None:
            raise ProtocolError("successful response cannot contain an error")
        if not self.ok and not self.error:
            raise ProtocolError("failed response must contain an error")
        _check_safe(self.result, "result")

    def to_mapping(self) -> dict[str, Any]:
        value: dict[str, Any] = {"version": self.version, "id": self.request_id, "ok": self.ok}
        value["result"] = dict(self.result)
        if self.error is not None:
            value["error"] = self.error
        return value

    def to_json(self) -> str:
        return json.dumps(self.to_mapping(), sort_keys=True, separators=(",", ":"))


def dispatch(request: Mapping[str, Any], provider: Any) -> Response:
    """Validate and dispatch one request to a provider adapter.

    Provider methods receive only the validated payload.  An absent method is
    an explicit unsupported-operation response, which lets managers discover
    provider capability without coupling to implementation details.
    """
    try:
        parsed = Request.from_mapping(request)
    except ProtocolError as exc:
        request_id = str(request.get("id", "invalid")) if isinstance(request, Mapping) else "invalid"
        return Response(request_id, False, error=str(exc))
    method = getattr(provider, parsed.operation.replace("-", "_"), None)
    if method is None:
        return Response(parsed.request_id, False, error=f"unsupported operation: {parsed.operation}")
    try:
        result = method(dict(parsed.payload))
        if not isinstance(result, Mapping):
            raise ProtocolError("provider result must be an object")
        _check_safe(result, "result")
        return Response(parsed.request_id, True, result=dict(result))
    except (ProtocolError, ValueError, TypeError) as exc:
        return Response(parsed.request_id, False, error=str(exc))
