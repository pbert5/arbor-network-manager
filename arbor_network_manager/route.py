"""Deterministic constrained shortest-path solving."""

from dataclasses import dataclass
import heapq
from typing import FrozenSet, List, Optional, Tuple

from .model import Edge, Health, NetworkSnapshot


@dataclass(frozen=True)
class RouteConstraints:
    capability: str = "ssh"
    avoid_networks: FrozenSet[str] = frozenset()
    avoid_providers: FrozenSet[str] = frozenset()
    require_private: bool = False
    max_hops: Optional[int] = None


@dataclass(frozen=True)
class RoutePlan:
    source: str
    target: str
    capability: str
    nodes: Tuple[str, ...]
    edges: Tuple[Edge, ...]
    cost: int
    snapshot_digest: str
    rejected: Tuple[str, ...] = ()

    @property
    def reachable(self) -> bool:
        return bool(self.edges) or self.source == self.target

    def explain(self) -> str:
        if not self.reachable:
            return f"No {self.capability}-capable route from {self.source} to {self.target}.\n" + "\n".join(self.rejected)
        lines = [f"selected {self.capability} route (cost {self.cost}):"]
        for edge in self.edges:
            suffix = f" ({edge.reason})" if edge.reason else ""
            lines.append(f"  {edge.source} -[{edge.network}/{edge.provider}]-> {edge.target}{suffix}")
        return "\n".join(lines)


class RouteSolver:
    """Dijkstra with explicit transit checks and stable lexical tie-breaking."""

    def solve(self, snapshot: NetworkSnapshot, source: str, target: str, constraints: RouteConstraints = RouteConstraints()) -> RoutePlan:
        rejected: List[str] = []
        if source == target:
            return RoutePlan(source, target, constraints.capability, (source,), (), 0, snapshot.digest)
        adjacency = {}
        for edge in snapshot.edges:
            if edge.endpoint_revoked:
                rejected.append(f"{edge.network}: endpoint generation is revoked")
                continue
            if not snapshot.endpoint_is_usable(edge):
                rejected.append(f"{edge.source}->{edge.target} via {edge.network}: stale or unaccepted endpoint generation")
                continue
            if edge.network in constraints.avoid_networks:
                rejected.append(f"{edge.network}: excluded by policy")
                continue
            if edge.provider in constraints.avoid_providers:
                rejected.append(f"{edge.provider}: excluded by policy")
                continue
            if constraints.require_private and not edge.private:
                rejected.append(f"{edge.network}: private endpoint required")
                continue
            if not edge.supports(constraints.capability):
                rejected.append(f"{edge.source}->{edge.target} via {edge.network}: missing {constraints.capability}")
                continue
            if edge.health == Health.UNREACHABLE:
                rejected.append(f"{edge.source}->{edge.target} via {edge.network}: provider unreachable")
                continue
            adjacency.setdefault(edge.source, []).append(edge)
        for edges in adjacency.values():
            edges.sort(key=lambda edge: (edge.cost + (10 if edge.health == Health.UNKNOWN else 0) + (5 if edge.health == Health.DEGRADED else 0), edge.network, edge.provider, edge.target))

        queue = [(0, (source,), source, ())]
        best = {}
        while queue:
            cost, path, node, used = heapq.heappop(queue)
            key = (node, len(path) - 1)
            if key in best and best[key] <= (cost, path):
                continue
            best[key] = (cost, path)
            if node == target:
                return RoutePlan(source, target, constraints.capability, path, used, cost, snapshot.digest, tuple(rejected))
            if constraints.max_hops is not None and len(used) >= constraints.max_hops:
                continue
            for edge in adjacency.get(node, ()):
                if edge.target in path:
                    rejected.append(f"{edge.source}->{edge.target}: cycle avoided")
                    continue
                if used and not used[-1].transit.allows(constraints.capability):
                    rejected.append(f"{node}: transit not authorized for {constraints.capability}")
                    continue
                penalty = 10 if edge.health == Health.UNKNOWN else 5 if edge.health == Health.DEGRADED else 0
                heapq.heappush(queue, (cost + edge.cost + penalty, path + (edge.target,), edge.target, used + (edge,)))
        return RoutePlan(source, target, constraints.capability, (), (), 0, snapshot.digest, tuple(sorted(set(rejected))))
