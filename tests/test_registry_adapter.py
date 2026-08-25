import unittest

from arbor_network_manager.registry_adapter import RegistryStateError, snapshot_from_registry_state


class RegistryAdapterTests(unittest.TestCase):
    def test_only_accepted_endpoint_records_enter_snapshot(self):
        snapshot = snapshot_from_registry_state({
            "format": "arbor-registry/accepted-state",
            "accepted": [
                {"schema": "endpoint", "recordId": "e1", "generation": 3, "payload": {
                    "id": "e1", "node": "target", "network": "lan", "provider": "lan",
                    "address": "10.0.0.2", "capabilities": ["ssh"],
                }},
                {"schema": "endpoint", "status": "quarantined", "payload": {
                    "node": "bad", "network": "lan", "provider": "lan", "address": "bad",
                }},
            ],
        })
        self.assertEqual([item.node for item in snapshot.endpoints], ["target"])

    def test_unknown_provider_and_unsupported_version_are_rejected(self):
        with self.assertRaises(RegistryStateError):
            snapshot_from_registry_state({"accepted": [{"schema": "endpoint", "payload": {
                "node": "x", "network": "n", "provider": "future", "address": "x", "generation": 1,
            }}]})
        with self.assertRaises(RegistryStateError):
            snapshot_from_registry_state({"version": 2, "accepted": []})


if __name__ == "__main__":
    unittest.main()
