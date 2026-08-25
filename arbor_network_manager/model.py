"""Small, JSON-friendly runtime model.

Registry authority, provider health, and route edges are deliberately separate
objects.  A reachable endpoint is not an authorization grant.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import FrozenSet, Mapping, Tuple


class Health(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"
    UNREACHABLE = "unreachable"


@dataclass(frozen=True)
class Endpoint:
    node: str
    network: str
    provider: str
    address: str
    generation: int
    capabilities: FrozenSet[str] = frozenset()
    revoked: bool = False
    identity_generation: int | None = None
    ssh_host_generation: int | None = None


@dataclass(frozen=True)
class EndpointObservation:
    """A provider fact; it is never an authorization grant."""

    node: str
    network: str
    provider: str
    address: str
    generation: int
    health: Health = Health.UNKNOWN
    capabilities: FrozenSet[str] = frozenset()
    reachable: bool | None = None


@dataclass(frozen=True)
class Transit:
    ssh: bool = False
    deploy: bool = False
    network: bool = False

    def allows(self, capability: str) -> bool:
        if capability == "ssh":
            return self.ssh
        if capability == "deploy":
            return self.deploy
        return self.network


@dataclass(frozen=True)
class Vertex:
    node: str
    authority: bool = True


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    network: str
    provider: str
    cost: int
    health: Health = Health.HEALTHY
    capabilities: FrozenSet[str] = frozenset()
    transit: Transit = Transit()
    endpoint_generation: int = 0
    endpoint_revoked: bool = False
    private: bool = False
    reason: str = ""

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities


@dataclass(frozen=True)
class NetworkSnapshot:
    vertices: Tuple[Vertex, ...]
    edges: Tuple[Edge, ...]
    endpoints: Tuple[Endpoint, ...] = ()
    digest: str = ""
    observations: Tuple[EndpointObservation, ...] = ()
    strict_authority: bool = False

    def node_names(self) -> FrozenSet[str]:
        return frozenset(vertex.node for vertex in self.vertices)

    def endpoint_is_usable(self, edge: Edge) -> bool:
        """Return whether an edge's advertised endpoint is accepted.

        Strict Registry-derived snapshots require both accepted authority and
        a matching current provider observation.  Explicit compatibility
        snapshots retain the historical graph-only behavior.
        """
        if edge.endpoint_revoked:
            return False
        accepted = tuple(
            endpoint for endpoint in self.endpoints
            if endpoint.node == edge.target
            and endpoint.network == edge.network
            and endpoint.provider == edge.provider
            and endpoint.generation == edge.endpoint_generation
            and not endpoint.revoked
        )
        if not accepted:
            return not self.strict_authority and not self.endpoints
        if not self.strict_authority and not self.observations:
            return True
        return any(
            observation.node == edge.target
            and observation.network == edge.network
            and observation.provider == edge.provider
            and observation.generation == edge.endpoint_generation
            and observation.reachable is not False
            and observation.health not in (Health.UNREACHABLE,)
            for observation in self.observations
        )


def _parse_endpoint(item: Mapping[str, object], *, accepted: bool) -> Endpoint | EndpointObservation:
    required = ("node", "network", "provider", "address", "generation")
    missing = [key for key in required if key not in item]
    if missing:
        raise ValueError(f"endpoint missing required fields: {', '.join(missing)}")
    common = dict(
        node=str(item["node"]), network=str(item["network"]),
        provider=str(item["provider"]), address=str(item["address"]),
        generation=int(item["generation"]),
        capabilities=frozenset(str(x) for x in item.get("capabilities", [])),
    )
    if accepted:
        return Endpoint(
            **common, revoked=bool(item.get("revoked", False)),
            identity_generation=(None if item.get("identityGeneration") is None else int(item["identityGeneration"])),
            ssh_host_generation=(None if item.get("sshHostGeneration") is None else int(item["sshHostGeneration"])),
        )
    return EndpointObservation(
        **common,
        health=Health(str(item.get("health", Health.UNKNOWN.value))),
        reachable=item.get("reachable") if item.get("reachable") is None else bool(item["reachable"]),
    )


def _parse_snapshot(value: Mapping[str, object], *, strict: bool) -> NetworkSnapshot:
    vertices = tuple(Vertex(node=str(item["node"])) for item in value.get("vertices", []))
    endpoints = tuple(_parse_endpoint(item, accepted=True) for item in value.get("endpoints", []))
    if strict and not endpoints and vertices:
        raise ValueError("accepted Registry snapshot must contain endpoint records")
    by_key: dict[tuple[str, str, str, int], Endpoint] = {}
    for item in endpoints:
        key = (item.node, item.network, item.provider, item.generation)
        previous = by_key.get(key)
        if previous is not None and previous != item:
            raise ValueError("duplicate conflicting accepted endpoint records")
        by_key[key] = item
    edges = tuple(_parse_edge(item) for item in value.get("edges", []))
    observations = tuple(_parse_endpoint(item, accepted=False) for item in value.get("observations", []))
    return NetworkSnapshot(vertices, edges, endpoints, str(value.get("digest", "")), observations, strict)


def _parse_edge(item: Mapping[str, object]) -> Edge:
    transit_value = item.get("transit", {})
    if not isinstance(transit_value, Mapping):
        raise ValueError("edge transit must be an object")
    return Edge(
        source=str(item["source"]), target=str(item["target"]),
        network=str(item["network"]), provider=str(item["provider"]),
        cost=int(item["cost"]), health=Health(str(item.get("health", Health.UNKNOWN.value))),
        capabilities=frozenset(str(x) for x in item.get("capabilities", [])),
        transit=Transit(ssh=bool(transit_value.get("ssh", False)),
                        deploy=bool(transit_value.get("deploy", False)),
                        network=bool(transit_value.get("network", False))),
        endpoint_generation=int(item.get("endpointGeneration", 0)),
        endpoint_revoked=bool(item.get("endpointRevoked", False)),
        private=bool(item.get("private", False)), reason=str(item.get("reason", "")),
    )


def snapshot_from_registry_mapping(value: Mapping[str, object]) -> NetworkSnapshot:
    """Parse strong accepted Registry state; endpoint authority is mandatory."""
    return _parse_snapshot(value, strict=True)


def snapshot_from_compatibility_mapping(value: Mapping[str, object]) -> NetworkSnapshot:
    """Parse legacy graph-only data without pretending it is accepted state."""
    return _parse_snapshot(value, strict=False)


def snapshot_from_mapping(value: Mapping[str, object]) -> NetworkSnapshot:
    """Parse accepted state. Use the explicitly named compatibility parser for graph-only data."""
    return snapshot_from_registry_mapping(value)
