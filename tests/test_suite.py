"""
tests/test_suite.py
~~~~~~~~~~~~~~~~~~~
Automated unit test suite verifying:
- Input validation (UID, region, JWT format)
- Protobuf encryption and encoding
- Usage tracking persistence
- API endpoints (authentication, validation, error handling)
- Token bridge logic
"""

import json
import os
import sys
import unittest

# Ensure project root is on sys.path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app import (
    app,
    API_KEY,
    validate_uid,
    validate_jwt_format,
    UsageTracker,
    enc,
    create_protobuf_message,
)
import generator_bridge


class TestAppSecurityAndValidation(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_uid_validation(self):
        self.assertTrue(validate_uid("12747380350"))
        self.assertTrue(validate_uid("1234567"))
        self.assertFalse(validate_uid("abc"))
        self.assertFalse(validate_uid("-500"))
        self.assertFalse(validate_uid("12"))  # too short
        self.assertFalse(validate_uid(""))
        self.assertFalse(validate_uid(None))

    def test_jwt_validation(self):
        valid_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozGz"
        self.assertTrue(validate_jwt_format(valid_jwt))
        self.assertFalse(validate_jwt_format("random_string_not_jwt"))
        self.assertFalse(validate_jwt_format("only.two.parts.extra"))
        self.assertFalse(validate_jwt_format("notey.payload.sig"))
        self.assertFalse(validate_jwt_format(""))

    def test_usage_tracker_persistence(self):
        initial = UsageTracker.get_used_count()
        self.assertIsInstance(initial, int)
        incremented = UsageTracker.increment()
        self.assertEqual(incremented, initial + 1)
        self.assertEqual(UsageTracker.get_used_count(), initial + 1)

    def test_protobuf_encryption(self):
        encrypted = enc("12747380350")
        self.assertIsNotNone(encrypted)
        self.assertIsInstance(encrypted, str)
        self.assertTrue(len(encrypted) > 10)

        proto_msg = create_protobuf_message("12747380350", "ME")
        self.assertIsNotNone(proto_msg)
        self.assertIsInstance(proto_msg, bytes)

    def test_dashboard_endpoint(self):
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"ARAFAT FLEX", res.data)

    def test_remain_endpoint_auth(self):
        # Without key -> 401
        res = self.client.get('/remain')
        self.assertEqual(res.status_code, 401)

        # With query key -> 200
        res = self.client.get(f'/remain?key={API_KEY}')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("remaining", data)
        self.assertIn("daily_limit", data)

        # With header key -> 200
        res = self.client.get('/remain', headers={"X-API-Key": API_KEY})
        self.assertEqual(res.status_code, 200)

    def test_tokens_status_endpoint_auth(self):
        res = self.client.get('/tokens/status')
        self.assertEqual(res.status_code, 401)

        res = self.client.get('/tokens/status', headers={"X-API-Key": API_KEY})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("regions", data)
        self.assertIn("ME", data["regions"])

    def test_tokens_add_validation(self):
        # Invalid JWT input
        res = self.client.post('/tokens/add', headers={"X-API-Key": API_KEY}, json={
            "region": "ME",
            "tokens": "garbage_not_a_jwt_token"
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("No valid JWT tokens found", res.get_json()["error"])

        # Valid JWT input
        dummy_jwt = "eyJhbGciOiJIUzI1NiJ9.eyJ1aWQiOiI5OTkifQ.dummy_signature_sample_test"
        res = self.client.post('/tokens/add', headers={"X-API-Key": API_KEY}, json={
            "region": "ME",
            "tokens": dummy_jwt
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "success")

        # Clean up test token
        generator_bridge.read_tokens("ME")
        filepath = generator_bridge.get_token_filepath("ME")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump([], f)

    def test_generate_input_validation(self):
        # Non-numeric count
        res = self.client.get(f'/generate?region=ME&count=invalid_number&key={API_KEY}')
        self.assertEqual(res.status_code, 400)
        self.assertIn("must be valid integers", res.get_json()["error"])

        # Unsupported region
        res = self.client.get(f'/generate?region=INVALID_XYZ&count=10&key={API_KEY}')
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid region", res.get_json()["error"])

    def test_like_input_validation(self):
        # Missing UID
        res = self.client.get(f'/like?region=ME&key={API_KEY}')
        self.assertEqual(res.status_code, 400)

        # Invalid UID (letters)
        res = self.client.get(f'/like?uid=abc1234&region=ME&key={API_KEY}')
        self.assertEqual(res.status_code, 400)

        # Invalid region
        res = self.client.get(f'/like?uid=12747380350&region=UNKNOWN&key={API_KEY}')
        self.assertEqual(res.status_code, 400)


class TestBridge(unittest.TestCase):
    def test_region_mapping(self):
        self.assertEqual(generator_bridge.map_to_tsun_region("ME"), "ME")
        self.assertEqual(generator_bridge.map_to_tsun_region("BD"), "BD")
        self.assertEqual(generator_bridge.map_to_tsun_region("US"), "SAC")

        with self.assertRaises(ValueError):
            generator_bridge.map_to_tsun_region("NON_EXISTENT_REGION")


if __name__ == '__main__':
    unittest.main()
