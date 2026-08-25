import unittest

from arbor_network_manager import snapshot_from_compatibility_mapping, snapshot_from_registry_mapping


class AuthorityParserTests(unittest.TestCase):
    def test_registry_parser_retains_endpoint_records(self):
        snapshot = snapshot_from_registry_mapping({
            "vertices": [{"node": "target"}],
            "endpoints": [{
                "node": "target", "network": "lan", "provider": "lan",
                "address": "10.0.0.2", "generation": 4,
            }],
        })
        self.assertTrue(snapshot.strict_authority)
        self.assertEqual(snapshot.endpoints[0].generation, 4)

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


if __name__ == "__main__":
    unittest.main()
