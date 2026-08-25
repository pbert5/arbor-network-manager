import unittest

from arbor_network_manager import (
    Edge, EndpointObservation, RouteSolver, Transit, Vertex, NetworkSnapshot,
    snapshot_from_compatibility_mapping,
    snapshot_from_registry_mapping,
)


class AuthorityParserTests(unittest.TestCase):
    def test_registry_parser_retains_endpoint_records(self):
        snapshot = snapshot_from_registry_mapping({
            "vertices": [{"node": "target"}],
            "edges": [{"source": "source", "target": "target", "network": "lan", "provider": "lan", "cost": 1, "endpointGeneration": 4}],
            "endpoints": [{
                "node": "target", "network": "lan", "provider": "lan",
                "address": "10.0.0.2", "generation": 4,
            }],
        })
        self.assertTrue(snapshot.strict_authority)
        self.assertEqual(snapshot.endpoints[0].generation, 4)
        self.assertTrue(snapshot.endpoint_is_usable(snapshot.edges[0]))
        self.assertFalse(snapshot.endpoint_is_reachable(snapshot.edges[0]))

    def test_missing_endpoint_is_rejected_in_registry_mode(self):
        with self.assertRaises(ValueError):
            snapshot_from_registry_mapping({"vertices": [{"node": "target"}]})

    def test_graph_only_mode_is_explicit(self):
        snapshot = snapshot_from_compatibility_mapping({"vertices": [{"node": "target"}]})
        self.assertFalse(snapshot.strict_authority)

    def test_conflicting_duplicate_is_rejected(self):
        endpoint = {
            "node": "target", "network": "lan", "provider": "lan",
            "address": "10.0.0.2", "generation": 4,
        }
        with self.assertRaises(ValueError):
            snapshot_from_registry_mapping({
                "vertices": [{"node": "target"}],
                "endpoints": [endpoint, {**endpoint, "address": "10.0.0.9"}],
            })

    def test_strict_snapshot_requires_current_observation(self):
        snapshot = snapshot_from_registry_mapping({
            "vertices": [{"node": "source"}, {"node": "target"}],
            "endpoints": [{
                "node": "target", "network": "lan", "provider": "lan",
                "address": "10.0.0.2", "generation": 4,
                "identityGeneration": 2, "sshHostGeneration": 7,
            }],
            "edges": [{
                "source": "source", "target": "target", "network": "lan",
                "provider": "lan", "cost": 1, "endpointGeneration": 4,
                "capabilities": ["ssh"], "transit": {"ssh": True},
            }],
        })
        self.assertFalse(RouteSolver().solve(snapshot, "source", "target").reachable)
        observed = NetworkSnapshot(
            snapshot.vertices, snapshot.edges, snapshot.endpoints, snapshot.digest,
            (EndpointObservation("target", "lan", "lan", "10.0.0.2", 4, reachable=True),), True,
        )
        plan = RouteSolver().solve(observed, "source", "target")
        self.assertTrue(plan.reachable)
        self.assertTrue(plan.bind(observed).binding.revalidate(observed))
        changed = NetworkSnapshot(
            observed.vertices, observed.edges, tuple(observed.endpoints[:0]), "digest-2",
            observed.observations, True,
        )
        self.assertFalse(plan.bind(observed).binding.revalidate(changed))


if __name__ == "__main__":
    unittest.main()
