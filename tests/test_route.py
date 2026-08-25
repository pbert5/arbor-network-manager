import unittest

from arbor_network_manager import Edge, Health, NetworkSnapshot, RouteConstraints, RouteSolver, Transit, Vertex


def graph(*edges):
    names = {x for edge in edges for x in (edge.source, edge.target)}
    return NetworkSnapshot(tuple(Vertex(name) for name in sorted(names)), tuple(edges), digest="snapshot-1")


class RouteTests(unittest.TestCase):
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
