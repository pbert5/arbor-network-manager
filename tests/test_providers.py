import unittest

from arbor_network_manager.providers import TailscaleProvider, YggDynamicPeerProvider


class ProviderBoundaryTests(unittest.TestCase):
    def test_tailscale_is_explicitly_unconfigured_and_not_healthy(self):
        provider = TailscaleProvider()
        self.assertFalse(provider.status({})["ready"])
        self.assertEqual(provider.health({})["health"], "unknown")

    def test_ygg_desired_peers_are_idempotent_and_generation_bound(self):
        provider = YggDynamicPeerProvider()
        peers = [{"node": "b", "generation": 2}, {"node": "a", "generation": 3}]
        self.assertEqual(provider.apply_peers({"peers": peers})["count"], 2)
        self.assertEqual([peer["node"] for peer in provider.desired], ["a", "b"])
        self.assertEqual(provider.apply_peers({"peers": peers})["applied"], True)
        with self.assertRaises(ValueError):
            provider.apply_peers({"peers": [{"node": "public-discovery"}]})


if __name__ == "__main__":
    unittest.main()
