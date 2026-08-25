"""Small operator daemon around the pure runtime manager."""

from __future__ import annotations

import argparse
import json
import os
import socketserver
import threading
import time
from typing import Any, Mapping

from .model import NetworkSnapshot, snapshot_from_registry_mapping
from .registry_adapter import snapshot_from_registry_state
from .transport import SocketProvider
from .provider_protocol import PROTOCOL_VERSION
from .route import RouteConstraints, RouteSolver
from .runtime import RuntimeManager


class NetworkDaemon:
    def __init__(self, accepted: NetworkSnapshot, providers: Mapping[str, Any] = {}) -> None:
        self.accepted = accepted
        self.runtime = RuntimeManager()
        for name, provider in providers.items():
            self.runtime.register(name, provider)
        self.snapshot = accepted
        self.last_reload_error: str | None = None

    def reconcile(self) -> NetworkSnapshot:
        self.snapshot = self.runtime.reconcile(self.accepted)
        return self.snapshot

    def reload(self, value: Mapping[str, Any]) -> bool:
        try:
            accepted = (
                snapshot_from_registry_state(value)
                if "accepted" in value or value.get("format") == "arbor-registry/accepted-state"
                else snapshot_from_registry_mapping(value)
            )
            self.accepted = accepted
            self.reconcile()
            self.last_reload_error = None
            return True
        except (KeyError, TypeError, ValueError) as exc:
            self.last_reload_error = str(exc)
            return False

    def request(self, operation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if operation in {"status", "providers", "endpoints", "snapshot", "export"}:
            snapshot = self.snapshot
            if operation == "status":
                return {"ready": self.runtime.ready(), "digest": snapshot.digest, "providers": [state.name for state in self.runtime.states], "reloadError": self.last_reload_error}
            if operation == "providers":
                return {"providers": [{"name": state.name, "ready": state.ready, "health": state.health.value, "capabilities": list(state.capabilities), "error": state.error} for state in self.runtime.states]}
            if operation == "endpoints":
                return {"accepted": [endpoint.__dict__ for endpoint in snapshot.endpoints], "observed": [endpoint.__dict__ for endpoint in snapshot.observations]}
            return {"snapshot": snapshot.__dict__}
        if operation == "route":
            plan = RouteSolver().solve(
                self.snapshot, str(payload["source"]), str(payload["target"]),
                RouteConstraints(capability=str(payload.get("capability", "ssh"))),
            )
            bound = plan.bind(self.snapshot) if plan.reachable and self.snapshot.strict_authority else plan
            return {
                "reachable": plan.reachable, "nodes": plan.nodes, "cost": plan.cost,
                "explanation": plan.explain(), "edges": [edge.__dict__ for edge in plan.edges],
                "binding": None if bound.binding is None else bound.binding.__dict__,
            }
        raise ValueError(f"unsupported daemon operation: {operation}")


class _DaemonHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        line = self.rfile.readline(1_048_577)
        if len(line) > 1_048_576:
            return
        try:
            request = json.loads(line.decode())
            result = self.server.daemon.request(request["operation"], request.get("payload", {}))  # type: ignore[attr-defined]
            response = {"version": PROTOCOL_VERSION, "id": request.get("id", "invalid"), "ok": True, "result": result}
        except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            response = {"version": PROTOCOL_VERSION, "id": "invalid", "ok": False, "error": str(exc)}
        self.wfile.write((json.dumps(response, sort_keys=True, default=str) + "\n").encode())


def serve(daemon: NetworkDaemon, path: str, registry_state: str | None = None, interval: float = 1.0) -> None:
    try:
        if os.path.exists(path):
            os.unlink(path)
    except OSError as exc:
        raise OSError(f"cannot replace network daemon socket {path}: {exc}") from exc
    server = socketserver.ThreadingUnixStreamServer(path, _DaemonHandler)
    server.daemon = daemon  # type: ignore[attr-defined]
    stop = threading.Event()

    def watch() -> None:
        last_mtime: int | None = None
        while not stop.wait(interval):
            try:
                mtime = os.stat(registry_state).st_mtime_ns  # type: ignore[arg-type]
                if mtime == last_mtime:
                    daemon.reconcile()
                    continue
                with open(registry_state, encoding="utf-8") as handle:  # type: ignore[arg-type]
                    daemon.reload(json.load(handle))
                last_mtime = mtime
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                # Retain the last accepted snapshot; status exposes the error
                # after a parse failure without logging state contents.
                daemon.last_reload_error = "Registry state unavailable or invalid"

    watcher = threading.Thread(target=watch, daemon=True) if registry_state else None
    try:
        daemon.reconcile()
        if watcher:
            watcher.start()
        server.serve_forever()
    finally:
        stop.set()
        server.server_close()
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry-snapshot", required=True)
    parser.add_argument("--socket", default="/run/arbor/networkd.sock")
    parser.add_argument("--provider", action="append", default=[], metavar="NAME=SOCKET")
    parser.add_argument("--watch-interval", type=float, default=1.0)
    args = parser.parse_args()
    with open(args.registry_snapshot, encoding="utf-8") as handle:
        initial = json.load(handle)
    accepted = (
        snapshot_from_registry_state(initial)
        if "accepted" in initial or initial.get("format") == "arbor-registry/accepted-state"
        else snapshot_from_registry_mapping(initial)
    )
    providers = {}
    for specification in args.provider:
        if "=" not in specification:
            raise SystemExit("--provider must use NAME=SOCKET")
        name, path = specification.split("=", 1)
        if not name or not path:
            raise SystemExit("--provider must use NAME=SOCKET")
        providers[name] = SocketProvider(path)
    os.makedirs(os.path.dirname(args.socket), mode=0o750, exist_ok=True)
    serve(NetworkDaemon(accepted, providers), args.socket, args.registry_snapshot, args.watch_interval)
