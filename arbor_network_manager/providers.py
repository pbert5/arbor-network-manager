"""Small provider adapters that report facts and never select routes."""

from __future__ import annotations

import json
import subprocess
import argparse
import time
from typing import Any, Mapping


class LanProvider:
    def __init__(self, node: str, interface: str | None = None, network: str = "lan") -> None:
        self.node = node
        self.interface = interface
        self.network = network

    def capabilities(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"capabilities": ["local-endpoints", "local-identities", "health"]}

    def status(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"ready": bool(self._addresses()), "health": "unknown"}

    def local_endpoints(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"endpoints": [{
            "node": self.node, "network": self.network, "address": address,
            "generation": int(payload.get("generation", 0)), "capabilities": ["ssh"],
            "health": "unknown", "reachable": True,
        } for address in self._addresses()]}

    def health(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        endpoints = []
        for target in payload.get("targets", []):
            if not isinstance(target, Mapping):
                continue
            address = str(target.get("address", ""))
            health, reachable = self._probe(address)
            endpoints.append({
                "node": target["node"], "network": target["network"],
                "address": address, "generation": target["generation"],
                "health": health, "reachable": reachable,
                "capabilities": target.get("capabilities", []),
            })
        return {"health": "unknown", "scope": "path", "endpoints": endpoints}

    @staticmethod
    def _probe(address: str) -> tuple[str, bool | None]:
        if not address:
            return "unknown", None
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "1", address],
                check=False, capture_output=True, timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            return "unknown", None
        return ("healthy", True) if result.returncode == 0 else ("unreachable", False)

    def _addresses(self) -> list[str]:
        command = ["ip", "-j", "addr", "show"]
        if self.interface:
            command.append(self.interface)
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=2)
            interfaces = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
            return []
        return [address["local"] for interface in interfaces for address in interface.get("addr_info", []) if address.get("local")]


class TailscaleProvider:
    """Configuration boundary; control-plane credentials stay external."""

    def capabilities(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"capabilities": ["local-endpoints", "health"]}

    def status(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"ready": False, "health": "unknown", "reason": "control-plane adapter not configured"}

    def local_endpoints(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"endpoints": []}

    def health(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"health": "unknown", "scope": "path"}


class YggDynamicPeerProvider:
    """Idempotent desired-peer boundary; discovery never grants trust."""

    def __init__(self) -> None:
        self.desired: tuple[dict[str, Any], ...] = ()

    def capabilities(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"capabilities": ["local-endpoints", "health", "dynamic-peers", "peer-health"]}

    def status(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"ready": True, "health": "unknown"}

    def local_endpoints(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"endpoints": list(payload.get("endpoints", []))}

    def health(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"health": "unknown", "scope": "path"}

    def apply_peers(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        peers = payload.get("peers", [])
        if not isinstance(peers, list):
            raise ValueError("peers must be a list")
        # Preserve accepted generation/provenance records exactly; no multicast
        # or observed public key is promoted into this desired state.
        normalized = []
        for peer in peers:
            if not isinstance(peer, Mapping) or not peer.get("node") or "generation" not in peer:
                raise ValueError("peer requires node and accepted generation")
            normalized.append(dict(peer))
        self.desired = tuple(sorted(normalized, key=lambda peer: (peer["node"], peer["generation"])))
        return {"applied": True, "count": len(self.desired)}


def lan_main() -> None:
    from .transport import ProviderSocketServer

    parser = argparse.ArgumentParser()
    parser.add_argument("--node", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--interface")
    args = parser.parse_args()
    server = ProviderSocketServer(args.socket, LanProvider(args.node, args.interface))
    server.start()
    try:
        while True:
            time.sleep(3600)
    finally:
        server.close()
