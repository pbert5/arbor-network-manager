"""Small provider adapters that report facts and never select routes."""

from __future__ import annotations

import json
import subprocess
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
        # LAN can establish local interface health, not remote target health.
        return {"health": "unknown", "scope": "local-interface"}

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
