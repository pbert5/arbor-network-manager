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
    reason: str = ""

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities


@dataclass(frozen=True)
class NetworkSnapshot:
    vertices: Tuple[Vertex, ...]
    edges: Tuple[Edge, ...]
    endpoints: Tuple[Endpoint, ...] = ()
    digest: str = ""

    def node_names(self) -> FrozenSet[str]:
        return frozenset(vertex.node for vertex in self.vertices)


def snapshot_from_mapping(value: Mapping[str, object]) -> NetworkSnapshot:
    """Parse the intentionally boring wire shape used by runtime adapters."""
    vertices = tuple(Vertex(node=str(item["node"])) for item in value.get("vertices", []))
    edges = []
    for item in value.get("edges", []):
        health = Health(str(item.get("health", Health.UNKNOWN.value)))
        transit_value = item.get("transit", {})
        edges.append(
            Edge(
                source=str(item["source"]),
                target=str(item["target"]),
                network=str(item["network"]),
                provider=str(item["provider"]),
                cost=int(item["cost"]),
                health=health,
                capabilities=frozenset(str(x) for x in item.get("capabilities", [])),
                transit=Transit(
                    ssh=bool(transit_value.get("ssh", False)),
                    deploy=bool(transit_value.get("deploy", False)),
                    network=bool(transit_value.get("network", False)),
                ),
                endpoint_generation=int(item.get("endpointGeneration", 0)),
                endpoint_revoked=bool(item.get("endpointRevoked", False)),
                reason=str(item.get("reason", "")),
            )
        )
    return NetworkSnapshot(vertices=vertices, edges=tuple(edges), digest=str(value.get("digest", "")))
