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
class ExecutionBinding:
    """Immutable identity and topology facts captured for sensitive execution."""

    source: str
    target: str
    target_identity_generation: int | None
    target_endpoint_generation: int | None
    target_ssh_host_generation: int | None
    jump_nodes: Tuple[str, ...]
    jump_identity_generations: Tuple[int | None, ...]
    jump_endpoint_generations: Tuple[int | None, ...]
    jump_ssh_host_generations: Tuple[int | None, ...]
    edge_networks: Tuple[str, ...]
    edge_providers: Tuple[str, ...]
    snapshot_digest: str
    route_digest: str
    capability: str

    def revalidate(self, snapshot: NetworkSnapshot) -> bool:
        if snapshot.digest != self.snapshot_digest:
            return False
        if self.capability not in {"ssh", "deploy", "network"}:
            return False
        endpoints = {(e.node, e.network, e.provider, e.generation): e for e in snapshot.endpoints if not e.revoked}
        current = tuple(snapshot.edges)
        expected_nodes = (self.source,) + self.jump_nodes + (self.target,)
        if len(self.edge_networks) != len(expected_nodes) - 1:
            return False
        for index, (network, provider) in enumerate(zip(self.edge_networks, self.edge_providers)):
            edge = next((e for e in current if e.source == expected_nodes[index]
                         and e.target == expected_nodes[index + 1]
                         and e.network == network and e.provider == provider), None)
            if edge is None or not snapshot.endpoint_is_reachable(edge) or edge.endpoint_generation != (
                self.target_endpoint_generation if index == len(self.edge_networks) - 1
                else self.jump_endpoint_generations[index]
            ):
                return False
        target = next((e for e in snapshot.endpoints if e.node == self.target and e.generation == self.target_endpoint_generation), None)
        if target is None:
            return False
        return (
            target.identity_generation == self.target_identity_generation
            and target.ssh_host_generation == self.target_ssh_host_generation
            and tuple(
                (node, identity, endpoint, ssh)
                for node, identity, endpoint, ssh in zip(
                    self.jump_nodes, self.jump_identity_generations,
                    self.jump_endpoint_generations, self.jump_ssh_host_generations,
                )
            ) == tuple(
                (node, next((e.identity_generation for e in snapshot.endpoints if e.node == node and e.generation == endpoint), None), endpoint,
                 next((e.ssh_host_generation for e in snapshot.endpoints if e.node == node and e.generation == endpoint), None))
                for node, endpoint in zip(self.jump_nodes, self.jump_endpoint_generations)
            )
        )


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
    binding: ExecutionBinding | None = None

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

    def bind(self, snapshot: NetworkSnapshot) -> "RoutePlan":
        if not self.reachable or snapshot.digest != self.snapshot_digest:
            raise ValueError("route cannot be bound to a different or unreachable snapshot")
        endpoints = {(e.node, e.network, e.provider, e.generation): e for e in snapshot.endpoints if not e.revoked}
        target_edge = self.edges[-1]
        target = endpoints.get((target_edge.target, target_edge.network, target_edge.provider, target_edge.endpoint_generation))
        if target is None:
            raise ValueError("target endpoint is not accepted in this snapshot")
        jumps = self.nodes[1:-1]
        jump_records = []
        for node, edge in zip(jumps, self.edges[:-1]):
            record = endpoints.get((node, edge.network, edge.provider, edge.endpoint_generation))
            if record is None:
                raise ValueError(f"jump endpoint is not accepted: {node}")
            jump_records.append(record)
        import hashlib
        material = repr((self.source, self.target, self.capability, self.nodes, self.edges, snapshot.digest)).encode()
        binding = ExecutionBinding(
            self.source, self.target, target.identity_generation, target.generation,
            target.ssh_host_generation, tuple(jumps),
            tuple(item.identity_generation for item in jump_records),
            tuple(item.generation for item in jump_records),
            tuple(item.ssh_host_generation for item in jump_records),
            tuple(edge.network for edge in self.edges), tuple(edge.provider for edge in self.edges),
            snapshot.digest, hashlib.sha256(material).hexdigest(), self.capability,
        )
        return RoutePlan(self.source, self.target, self.capability, self.nodes, self.edges, self.cost, self.snapshot_digest, self.rejected, binding)


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
            if not snapshot.endpoint_is_reachable(edge):
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
