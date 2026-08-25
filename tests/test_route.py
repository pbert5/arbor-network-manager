import unittest
from dataclasses import replace

from arbor_network_manager import Edge, Endpoint, Health, NetworkSnapshot, RouteConstraints, RouteSolver, Transit, Vertex


def graph(*edges):
    names = {x for edge in edges for x in (edge.source, edge.target)}
    return NetworkSnapshot(tuple(Vertex(name) for name in sorted(names)), tuple(edges), digest="snapshot-1")


def endpoint_graph(*edges, generation=1):
    endpoints = tuple(
        Endpoint(edge.target, edge.network, edge.provider, f"{edge.target}.example", generation)
        for edge in edges
    )
    return NetworkSnapshot(
        tuple(Vertex(name) for edge in edges for name in (edge.source, edge.target)),
        tuple(edges),
        endpoints=endpoints,
        digest="snapshot-1",
    )


class RouteTests(unittest.TestCase):
    def test_direct_endpoint_and_source_target_invariants(self):
        edge = Edge("local", "target", "lan", "lan", 1, capabilities=frozenset({"ssh"}), endpoint_generation=1)
        result = RouteSolver().solve(endpoint_graph(edge), "local", "target")
        self.assertTrue(result.reachable)
        self.assertEqual(result.nodes[0], "local")
        self.assertEqual(result.nodes[-1], "target")
        self.assertEqual(len(result.nodes), len(set(result.nodes)))

    def test_one_and_two_hop_transit(self):
        a = Edge("local", "jump", "lan", "lan", 1, capabilities=frozenset({"ssh"}), transit=Transit(ssh=True), endpoint_generation=1)
        b = Edge("jump", "target", "lan", "lan", 1, capabilities=frozenset({"ssh"}), transit=Transit(ssh=True), endpoint_generation=1)
        c = Edge("target", "far", "ygg", "ygg", 1, capabilities=frozenset({"ssh"}), transit=Transit(ssh=True), endpoint_generation=1)
        self.assertEqual(RouteSolver().solve(endpoint_graph(a, b), "local", "target").nodes, ("local", "jump", "target"))
        self.assertEqual(RouteSolver().solve(endpoint_graph(a, b, c), "local", "far").nodes, ("local", "jump", "target", "far"))

    def test_alternate_paths_health_and_deterministic_tie(self):
        paths = [
            Edge("local", "b", "lan", "z", 1, capabilities=frozenset({"ssh"}), transit=Transit(ssh=True)),
            Edge("b", "target", "lan", "z", 1, capabilities=frozenset({"ssh"}), transit=Transit(ssh=True)),
            Edge("local", "a", "lan", "a", 1, capabilities=frozenset({"ssh"}), transit=Transit(ssh=True)),
            Edge("a", "target", "lan", "a", 1, capabilities=frozenset({"ssh"}), transit=Transit(ssh=True)),
        ]
        self.assertEqual(RouteSolver().solve(graph(*paths), "local", "target").nodes, ("local", "a", "target"))
        degraded = replace(paths[2], health=Health.DEGRADED)
        self.assertEqual(RouteSolver().solve(graph(paths[0], paths[1], degraded, paths[3]), "local", "target").nodes, ("local", "b", "target"))

    def test_revoked_stale_and_unhealthy_endpoints_are_excluded(self):
        edge = Edge("local", "target", "lan", "lan", 1, capabilities=frozenset({"ssh"}), endpoint_generation=1)
        stale = endpoint_graph(replace(edge, endpoint_generation=1), generation=2)
        self.assertFalse(RouteSolver().solve(stale, "local", "target").reachable)
        revoked = endpoint_graph(replace(edge, endpoint_revoked=True))
        self.assertFalse(RouteSolver().solve(revoked, "local", "target").reachable)
        unhealthy = graph(replace(edge, health=Health.UNREACHABLE))
        self.assertFalse(RouteSolver().solve(unhealthy, "local", "target").reachable)

    def test_capability_transit_and_hop_constraints(self):
        first = Edge("local", "jump", "lan", "lan", 1, capabilities=frozenset({"ssh"}), transit=Transit(ssh=False))
        second = Edge("jump", "target", "lan", "lan", 1, capabilities=frozenset({"ssh"}), transit=Transit(ssh=True))
        denied = RouteSolver().solve(graph(first, second), "local", "target")
        self.assertFalse(denied.reachable)
        self.assertIn("transit", denied.explain())
        wrong_capability = RouteSolver().solve(graph(replace(first, capabilities=frozenset({"service"}))), "local", "jump", RouteConstraints(capability="ssh"))
        self.assertFalse(wrong_capability.reachable)
        limited = RouteSolver().solve(graph(replace(first, transit=Transit(ssh=True)), second), "local", "target", RouteConstraints(max_hops=1))
        self.assertFalse(limited.reachable)

    def test_provider_and_private_constraints(self):
        edge = Edge("local", "target", "lan", "lan", 1, capabilities=frozenset({"ssh"}), private=True)
        other = replace(edge, provider="tailscale", private=False, cost=0)
        result = RouteSolver().solve(graph(edge, other), "local", "target", RouteConstraints(avoid_providers=frozenset({"tailscale"}), require_private=True))
        self.assertEqual(result.edges, (edge,))

    def test_multiple_parents_unreachable_and_direct_identity(self):
        parent_a = Edge("a", "target", "lan", "lan", 1, capabilities=frozenset({"ssh"}), transit=Transit(ssh=True))
        parent_b = Edge("b", "target", "lan", "lan", 1, capabilities=frozenset({"ssh"}), transit=Transit(ssh=True))
        self.assertFalse(RouteSolver().solve(graph(parent_a, parent_b), "local", "target").reachable)
        self.assertTrue(RouteSolver().solve(graph(), "local", "local").reachable)
    def test_preference_and_failover(self):
        lan = Edge("local", "target", "lan", "lan", 10, capabilities=frozenset({"ssh"}), transit=Transit(ssh=True))
        ygg = Edge("local", "target", "privateYgg", "ygg", 25, capabilities=frozenset({"ssh"}), transit=Transit(ssh=True))
        self.assertEqual(RouteSolver().solve(graph(lan, ygg), "local", "target").edges, (lan,))
        failed = Edge(**{**ygg.__dict__, "cost": 25})
        self.assertEqual(RouteSolver().solve(graph(Edge(**{**lan.__dict__, "health": Health.UNREACHABLE}), failed), "local", "target").edges, (failed,))

    def test_transit_and_cycle(self):
        first = Edge("local", "jump", "lan", "lan", 10, capabilities=frozenset({"ssh"}), transit=Transit(ssh=True))
        second = Edge("jump", "target", "ygg", "ygg", 20, capabilities=frozenset({"ssh"}), transit=Transit(ssh=True))
        self.assertEqual(RouteSolver().solve(graph(first, second), "local", "target").nodes, ("local", "jump", "target"))
        denied = Edge(**{**first.__dict__, "transit": Transit()})
        self.assertFalse(RouteSolver().solve(graph(denied, second), "local", "target").reachable)

    def test_revocation_and_constraints(self):
        edge = Edge("local", "target", "publicYgg", "ygg", 1, capabilities=frozenset({"ssh"}), endpoint_revoked=True)
        result = RouteSolver().solve(graph(edge), "local", "target")
        self.assertFalse(result.reachable)
        self.assertIn("revoked", result.explain())


if __name__ == "__main__":
    unittest.main()
