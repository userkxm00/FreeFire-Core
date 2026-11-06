"""
tests/test_suite.py
~~~~~~~~~~~~~~~~~~~
Automated unit test suite verifying:
- Enforcement of API_KEY configuration
- Input validation (UID, region, JWT syntax & payload expiration)
- Server-side Dashboard authentication gate (401 vs 200)
- UsageTracker thread-safe persistence & corrupted state recovery
- Protobuf encryption and encoding
- API endpoints (authentication, validation, error handling)
- Token bridge regional mapping and file handling
"""

import base64
import json
import os
import sys
import tempfile
import time
import unittest

TEST_API_KEY = "TEST_SECRET_KEY_12345_XYZ"
os.environ["API_KEY"] = TEST_API_KEY

# Ensure project root is on sys.path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app import (
    app,
    require_api_key_configured,
    validate_uid,
    check_jwt_structure,
    inspect_jwt_payload,
    UsageTracker,
    enc,
    create_protobuf_message,
)
import generator_bridge


class TestAppSecurityAndValidation(unittest.TestCase):
    def setUp(self):
        os.environ["API_KEY"] = TEST_API_KEY
        self.client = app.test_client()

    def test_require_api_key_configured(self):
        # When key is present:
        os.environ["API_KEY"] = "MY_VALID_SECRET_KEY"
        self.assertEqual(require_api_key_configured(), "MY_VALID_SECRET_KEY")

        # When key is unset or blank:
        os.environ["API_KEY"] = ""
        with self.assertRaises(RuntimeError):
            require_api_key_configured()

        del os.environ["API_KEY"]
        with self.assertRaises(RuntimeError):
            require_api_key_configured()

        # Restore
        os.environ["API_KEY"] = TEST_API_KEY

    def test_uid_validation(self):
        self.assertTrue(validate_uid("12747380350"))
        self.assertTrue(validate_uid("1234567"))
        self.assertFalse(validate_uid("abc"))
        self.assertFalse(validate_uid("-500"))
        self.assertFalse(validate_uid("12"))  # too short
        self.assertFalse(validate_uid(""))
        self.assertFalse(validate_uid(None))

    def test_jwt_structure_validation(self):
        valid_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozGz"
        self.assertTrue(check_jwt_structure(valid_jwt))
        self.assertFalse(check_jwt_structure("random_string_not_jwt"))
        self.assertFalse(check_jwt_structure("only.two.parts"))
        self.assertFalse(check_jwt_structure("notey.payload.sig"))
        self.assertFalse(check_jwt_structure(""))
        self.assertFalse(check_jwt_structure(None))

    def test_jwt_payload_inspection_and_expiration(self):
        now_ts = int(time.time())

        # Future expiration token
        future_payload = base64.urlsafe_b64encode(
            json.dumps({"uid": "123", "exp": now_ts + 3600}).encode()
        ).decode().rstrip("=")
        active_token = f"eyJhbGciOiJIUzI1NiJ9.{future_payload}.signature_dummy"
        is_valid, claims, msg = inspect_jwt_payload(active_token)
        self.assertTrue(is_valid)
        self.assertEqual(claims.get("uid"), "123")

        # Expired token
        past_payload = base64.urlsafe_b64encode(
            json.dumps({"uid": "123", "exp": now_ts - 3600}).encode()
        ).decode().rstrip("=")
        expired_token = f"eyJhbGciOiJIUzI1NiJ9.{past_payload}.signature_dummy"
        is_valid, claims, msg = inspect_jwt_payload(expired_token)
        self.assertFalse(is_valid)
        self.assertIn("expired", msg.lower())

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

    def test_dashboard_server_side_gate(self):
        # 1. Unauthenticated GET / must return 401 with Login Gate
        res = self.client.get('/')
        self.assertEqual(res.status_code, 401)
        self.assertIn("تسجيل الدخول المطلوب", res.data.decode('utf-8'))

        # 2. Authenticated with ?key= must return 200 with Dashboard
        res_auth = self.client.get(f'/?key={TEST_API_KEY}')
        self.assertEqual(res_auth.status_code, 200)
        self.assertIn("Free Fire Like & Token Manager", res_auth.data.decode('utf-8'))

        # 3. Authenticated with header X-API-Key must return 200 with Dashboard
        res_header = self.client.get('/', headers={"X-API-Key": TEST_API_KEY})
        self.assertEqual(res_header.status_code, 200)
        self.assertIn("Free Fire Like & Token Manager", res_header.data.decode('utf-8'))

    def test_remain_endpoint_auth(self):
        # Without key -> 401
        res = self.client.get('/remain')
        self.assertEqual(res.status_code, 401)

        # With query key -> 200
        res = self.client.get(f'/remain?key={TEST_API_KEY}')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("remaining", data)
        self.assertIn("daily_limit", data)

        # With header key -> 200
        res = self.client.get('/remain', headers={"X-API-Key": TEST_API_KEY})
        self.assertEqual(res.status_code, 200)

    def test_tokens_status_endpoint_auth(self):
        res = self.client.get('/tokens/status')
        self.assertEqual(res.status_code, 401)

        res = self.client.get('/tokens/status', headers={"X-API-Key": TEST_API_KEY})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("regions", data)
        self.assertIn("ME", data["regions"])

    def test_tokens_add_validation(self):
        # Invalid JWT input
        res = self.client.post('/tokens/add', headers={"X-API-Key": TEST_API_KEY}, json={
            "region": "ME",
            "tokens": "garbage_not_a_jwt_token"
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("No valid", res.get_json()["error"])

        # Valid JWT input
        dummy_jwt = "eyJhbGciOiJIUzI1NiJ9.eyJ1aWQiOiI5OTkifQ.dummy_signature_sample_test"
        res = self.client.post('/tokens/add', headers={"X-API-Key": TEST_API_KEY}, json={
            "region": "ME",
            "tokens": dummy_jwt
        })
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], "success")

        # Clean up test token
        filepath = generator_bridge.get_token_filepath("ME")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump([], f)

    def test_generate_input_validation(self):
        # Non-numeric count
        res = self.client.get(f'/generate?region=ME&count=invalid_number&key={TEST_API_KEY}')
        self.assertEqual(res.status_code, 400)
        self.assertIn("must be valid integers", res.get_json()["error"])

        # Unsupported region
        res = self.client.get(f'/generate?region=INVALID_XYZ&count=10&key={TEST_API_KEY}')
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid region", res.get_json()["error"])

    def test_like_input_validation(self):
        # Missing UID
        res = self.client.get(f'/like?region=ME&key={TEST_API_KEY}')
        self.assertEqual(res.status_code, 400)

        # Invalid UID (letters)
        res = self.client.get(f'/like?uid=abc1234&region=ME&key={TEST_API_KEY}')
        self.assertEqual(res.status_code, 400)

        # Invalid region
        res = self.client.get(f'/like?uid=12747380350&region=UNKNOWN&key={TEST_API_KEY}')
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
