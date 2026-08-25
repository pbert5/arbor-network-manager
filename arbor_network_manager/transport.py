"""Bounded JSON-lines Unix-socket transport for provider adapters."""

from __future__ import annotations

import json
import socket
import socketserver
from threading import Thread
from typing import Any

from .provider_protocol import dispatch


class ProviderSocketClient:
    def __init__(self, path: str, timeout: float = 5.0) -> None:
        self.path = path
        self.timeout = timeout

    def request(self, request: dict[str, Any]) -> dict[str, Any]:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(self.timeout)
            connection.connect(self.path)
            connection.sendall((json.dumps(request, sort_keys=True) + "\n").encode())
            data = b""
            while not data.endswith(b"\n"):
                chunk = connection.recv(65536)
                if not chunk:
                    break
                data += chunk
                if len(data) > 1_048_576:
                    raise ValueError("provider response exceeds 1 MiB")
        if not data:
            raise ConnectionError("provider closed socket without a response")
        return json.loads(data.decode())


class _RequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        line = self.rfile.readline(1_048_577)
        if len(line) > 1_048_576:
            return
        try:
            request = json.loads(line.decode())
            response = dispatch(request, self.server.provider)  # type: ignore[attr-defined]
            self.wfile.write((response.to_json() + "\n").encode())
        except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
            self.wfile.write((json.dumps({"version": 1, "id": "invalid", "ok": False, "error": str(exc)}) + "\n").encode())


class ProviderSocketServer:
    def __init__(self, path: str, provider: Any) -> None:
        self.path = path
        self.provider = provider
        self._server = socketserver.ThreadingUnixStreamServer(path, _RequestHandler)
        self._server.daemon_threads = True
        self._server.provider = provider  # type: ignore[attr-defined]
        self._thread: Thread | None = None

    def start(self) -> None:
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

