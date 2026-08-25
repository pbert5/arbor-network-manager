import unittest

from arbor_network_manager.provider_protocol import Request, Response, dispatch


class Provider:
    def status(self, payload):
        return {"ready": True, "echo": payload.get("name", "")}

    def apply_peers(self, payload):
        return {"applied": sorted(payload.get("peers", []))}


class ProviderProtocolTests(unittest.TestCase):
    def test_request_is_versioned_and_deterministically_encoded(self):
        request = Request("r1", "status", {"name": "lan"})
        self.assertEqual(request.to_json(), '{"id":"r1","operation":"status","payload":{"name":"lan"},"version":1}')
        self.assertEqual(Request.from_mapping(request.to_mapping()), request)

    def test_dispatch_is_idempotent_at_desired_state_boundary(self):
        message = {"id": "r1", "operation": "apply-peers", "payload": {"peers": ["b", "a"]}}
        provider = Provider()
        first = dispatch(message, provider)
        second = dispatch(message, provider)
        self.assertEqual(first, second)
        self.assertEqual(first.to_mapping()["result"], {"applied": ["a", "b"]})

    def test_unsupported_and_malformed_requests_are_explicit(self):
        unsupported = dispatch({"id": "r2", "operation": "reconfigure", "payload": {}}, Provider())
        malformed = dispatch({"id": "r3", "operation": "status", "payload": {"auth_token": "sentinel"}}, Provider())
        self.assertFalse(unsupported.ok)
        self.assertIn("unsupported", unsupported.error)
        self.assertFalse(malformed.ok)
        self.assertIn("credential", malformed.error)

    def test_unsupported_provider_method_is_not_silently_ignored(self):
        response = dispatch({"id": "r4", "operation": "health", "payload": {}}, Provider())
        self.assertFalse(response.ok)
        self.assertEqual(response.error, "unsupported operation: health")

    def test_protocol_version_is_checked(self):
        response = dispatch({"id": "r5", "version": 99, "operation": "status", "payload": {}}, Provider())
        self.assertFalse(response.ok)
        self.assertIn("version", response.error)


if __name__ == "__main__":
    unittest.main()
