import unittest

from arbor_network_manager import Edge, Endpoint, Health, NetworkSnapshot, Transit, Vertex
from arbor_network_manager.runtime import RuntimeManager


class FakeProvider:
    def __init__(self):
        self.applied = []

    def status(self, payload):
        return {"ready": True, "health": "healthy"}

    def local_endpoints(self, payload):
        return {"endpoints": [{"node": "target", "network": "lan", "address": "10.0.0.2", "generation": 3, "capabilities": ["ssh"]}]}

    def health(self, payload):
        return {"health": "healthy"}

    def apply_peers(self, payload):
        self.applied.append(payload)
        return {"applied": True}


class CapabilityProvider(FakeProvider):
    def capabilities(self, payload):
        return {"capabilities": ["local-endpoints", "health"]}

    def health(self, payload):
        self.targets = payload["targets"]
        return {"health": "unknown", "endpoints": [{
            **payload["targets"][0], "health": "healthy", "reachable": True,
        }]} if payload["targets"] else {"health": "unknown", "endpoints": []}


class RuntimeTests(unittest.TestCase):
    def test_reconcile_uses_accepted_state_and_is_repeatable(self):
        provider = FakeProvider()
        manager = RuntimeManager()
        manager.register("lan", provider)
        endpoint = Endpoint("target", "lan", "lan", "10.0.0.2", 3, frozenset({"ssh"}))
        snapshot = NetworkSnapshot(
            (Vertex("local"), Vertex("target")),
            (Edge("local", "target", "lan", "lan", 1, capabilities=frozenset({"ssh"}), endpoint_generation=3),),
            (endpoint,), "digest-1")
        first = manager.reconcile(snapshot)
        second = manager.reconcile(snapshot)
        self.assertEqual(first, second)
        self.assertEqual(len(provider.applied), 2)
        self.assertTrue(manager.ready(("lan",)))
        self.assertEqual(first.edges[0].health, Health.HEALTHY)

    def test_revoked_and_unknown_provider_records_never_reach_provider(self):
        provider = FakeProvider()
        manager = RuntimeManager()
        manager.register("lan", provider)
        accepted = Endpoint("a", "lan", "lan", "10.0.0.3", 1)
        revoked = Endpoint("b", "lan", "lan", "10.0.0.4", 2, revoked=True)
        unknown = Endpoint("c", "future", "future", "10.0.0.5", 1)
        snapshot = NetworkSnapshot((Vertex("a"),), (), (accepted, revoked, unknown), "digest-2")
        manager.reconcile(snapshot)
        peers = provider.applied[-1]["peers"]
        self.assertEqual([peer["node"] for peer in peers], ["a"])

    def test_provider_without_dynamic_peers_is_not_called(self):
        provider = CapabilityProvider()
        manager = RuntimeManager()
        manager.register("lan", provider)
        manager.reconcile(NetworkSnapshot((Vertex("a"),), (), (), "digest-3"))
        self.assertEqual(provider.applied, [])

    def test_target_health_observation_is_joined_without_granting_authority(self):
        provider = CapabilityProvider()
        manager = RuntimeManager()
        manager.register("lan", provider)
        accepted = Endpoint("target", "lan", "lan", "10.0.0.2", 3, frozenset({"ssh"}))
        snapshot = NetworkSnapshot(
            (Vertex("source"), Vertex("target")),
            (Edge("source", "target", "lan", "lan", 1, capabilities=frozenset({"ssh"}), endpoint_generation=3),),
            (accepted,), "digest-target", True,
        )
        reconciled = manager.reconcile(snapshot)
        self.assertEqual(reconciled.edges[0].health, Health.HEALTHY)
        self.assertEqual(reconciled.endpoints, (accepted,))
        self.assertEqual(reconciled.observations[0].node, "target")


if __name__ == "__main__":
    unittest.main()
