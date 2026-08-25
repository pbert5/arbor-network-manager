"""Small operator daemon around the pure runtime manager."""

from __future__ import annotations

import argparse
import json
import os
import socketserver
from typing import Any, Mapping

from .model import NetworkSnapshot, snapshot_from_registry_mapping
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

    def reconcile(self) -> NetworkSnapshot:
        self.snapshot = self.runtime.reconcile(self.accepted)
        return self.snapshot

    def request(self, operation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if operation in {"status", "providers", "endpoints", "snapshot", "export"}:
            snapshot = self.snapshot
            if operation == "status":
                return {"ready": self.runtime.ready(), "digest": snapshot.digest, "providers": [state.name for state in self.runtime.states]}
            if operation == "providers":
                return {"providers": [{"name": state.name, "ready": state.ready, "health": state.health.value, "capabilities": list(state.capabilities)} for state in self.runtime.states]}
            if operation == "endpoints":
                return {"accepted": [endpoint.__dict__ for endpoint in snapshot.endpoints], "observed": [endpoint.__dict__ for endpoint in snapshot.observations]}
            return {"snapshot": snapshot.__dict__}
        if operation == "route":
            plan = RouteSolver().solve(
                self.snapshot, str(payload["source"]), str(payload["target"]),
                RouteConstraints(capability=str(payload.get("capability", "ssh"))),
            )
            return {"reachable": plan.reachable, "nodes": plan.nodes, "cost": plan.cost, "explanation": plan.explain()}
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


def serve(daemon: NetworkDaemon, path: str) -> None:
    server = socketserver.ThreadingUnixStreamServer(path, _DaemonHandler)
    server.daemon = daemon  # type: ignore[attr-defined]
    try:
        daemon.reconcile()
        server.serve_forever()
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry-snapshot", required=True)
    parser.add_argument("--socket", default="/run/arbor/networkd.sock")
    args = parser.parse_args()
    with open(args.registry_snapshot, encoding="utf-8") as handle:
        accepted = snapshot_from_registry_mapping(json.load(handle))
    os.makedirs(os.path.dirname(args.socket), mode=0o750, exist_ok=True)
    serve(NetworkDaemon(accepted), args.socket)

