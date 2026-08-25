import os
import tempfile
import unittest

from arbor_network_manager.daemon import NetworkDaemon
from arbor_network_manager.model import NetworkSnapshot, Vertex
from arbor_network_manager.transport import ProviderSocketClient, ProviderSocketServer


class Provider:
    def status(self, payload):
        return {"ready": True}


class TransportTests(unittest.TestCase):
    def test_provider_socket_round_trip_and_unsupported_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "provider.sock")
            server = ProviderSocketServer(path, Provider())
            server.start()
            try:
                client = ProviderSocketClient(path)
                response = client.request({"version": 1, "id": "one", "operation": "status", "payload": {}})
                self.assertTrue(response["ok"])
                response = client.request({"version": 1, "id": "two", "operation": "apply-peers", "payload": {}})
                self.assertFalse(response["ok"])
            finally:
                server.close()

    def test_daemon_reconstructs_from_accepted_snapshot(self):
        daemon = NetworkDaemon(NetworkSnapshot((Vertex("source"),), (), (), "digest"))
        self.assertEqual(daemon.request("status", {})["digest"], "digest")
        self.assertEqual(daemon.request("snapshot", {})["snapshot"]["digest"], "digest")


if __name__ == "__main__":
    unittest.main()
