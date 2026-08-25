"""Restart-safe reconciliation of accepted state with provider observations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Protocol

from .model import Edge, Endpoint, Health, NetworkSnapshot


class Provider(Protocol):
    def status(self, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def local_endpoints(self, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def health(self, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def apply_peers(self, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class ProviderState:
    name: str
    ready: bool = False
    health: Health = Health.UNKNOWN
    observed_endpoints: tuple[Endpoint, ...] = ()
    applied_generations: tuple[tuple[str, int], ...] = ()


class RuntimeManager:
    """Purely reconstructable runtime state; no hidden authority database.

    ``reconcile`` always receives the accepted Registry snapshot. Provider
    caches can disappear on restart; the next call reapplies the same desired
    peer set and rebuilds the graph from current observations.
    """

    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}
        self._states: dict[str, ProviderState] = {}

    def register(self, name: str, provider: Provider) -> None:
        self._providers[name] = provider
        self._states[name] = ProviderState(name)

    @property
    def states(self) -> tuple[ProviderState, ...]:
        return tuple(self._states[name] for name in sorted(self._states))

    def reconcile(self, accepted: NetworkSnapshot) -> NetworkSnapshot:
        accepted_by_provider: dict[str, list[Endpoint]] = {}
        for endpoint in accepted.endpoints:
            if not endpoint.revoked and endpoint.provider in self._providers:
                accepted_by_provider.setdefault(endpoint.provider, []).append(endpoint)

        observed: list[Endpoint] = []
        for name in sorted(self._providers):
            provider = self._providers[name]
            status = provider.status({})
            endpoint_payload = provider.local_endpoints({})
            health_payload = provider.health({})
            desired = accepted_by_provider.get(name, [])
            provider.apply_peers({"peers": [self._endpoint_record(item) for item in desired]})
            local = tuple(self._parse_endpoint(item, name) for item in endpoint_payload.get("endpoints", []))
            observed.extend(local)
            health = Health(str(health_payload.get("health", status.get("health", Health.UNKNOWN.value))))
            self._states[name] = ProviderState(
                name=name,
                ready=bool(status.get("ready", False)),
                health=health,
                observed_endpoints=local,
                applied_generations=tuple(sorted((item.node, item.generation) for item in desired)),
            )

        health_by_provider = {state.name: state.health for state in self.states}
        edges = tuple(
            replace(edge, health=health_by_provider.get(edge.provider, Health.UNREACHABLE))
            for edge in accepted.edges
            if edge.provider in self._providers and not edge.endpoint_revoked
        )
        return NetworkSnapshot(accepted.vertices, edges, tuple(observed), accepted.digest)

    def ready(self, required: tuple[str, ...] = ()) -> bool:
        return all(self._states.get(name, ProviderState(name)).ready for name in required)

    @staticmethod
    def _endpoint_record(endpoint: Endpoint) -> dict[str, Any]:
        return {"node": endpoint.node, "network": endpoint.network, "provider": endpoint.provider,
                "address": endpoint.address, "generation": endpoint.generation,
                "capabilities": sorted(endpoint.capabilities)}

    @staticmethod
    def _parse_endpoint(value: Mapping[str, Any], provider: str) -> Endpoint:
        return Endpoint(node=str(value["node"]), network=str(value["network"]), provider=provider,
                        address=str(value["address"]), generation=int(value["generation"]),
                        capabilities=frozenset(str(item) for item in value.get("capabilities", [])))
