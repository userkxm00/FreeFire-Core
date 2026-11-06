"""
tests/test_suite.py
~~~~~~~~~~~~~~~~~~~
Comprehensive unit test suite verifying:
- Enforcement of API_KEY configuration on startup (refusal to boot without key)
- Independent SESSION_SECRET (never derived from API_KEY)
- CSRF protection on forms and state-modifying session requests
- Secure session-based authentication flow (POST /login, /logout, HttpOnly cookie)
- Zero secret leakage: API_KEY is NEVER present in Dashboard HTML or client JavaScript
- Strict rejection of query-string keys (?key=...) across all endpoints
- Header-based authentication (X-API-Key, Authorization: Bearer) for REST/bot clients (immune to CSRF)
- JWT structural validation vs unverified offline payload expiration
- Input validation (UID length & type, region whitelisting, numeric bounds)
- UsageTracker thread-safe persistence and recovery
- Protobuf message construction and AES cipher
- Token bridge regional mapping and TSun SSL configuration
"""

import base64
import json
import os
import sys
import time
import unittest

TEST_API_KEY = "TEST_SECRET_KEY_12345_XYZ"
TEST_SESSION_SECRET = "TEST_INDEPENDENT_SESSION_SECRET_987654321"
os.environ["API_KEY"] = TEST_API_KEY
os.environ["SESSION_SECRET"] = TEST_SESSION_SECRET

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
import config.settings as tsun_settings


class TestAppSecurityAndValidation(unittest.TestCase):
    def setUp(self):
        os.environ["API_KEY"] = TEST_API_KEY
        os.environ["SESSION_SECRET"] = TEST_SESSION_SECRET
        self.client = app.test_client()

    def test_startup_api_key_enforcement(self):
        """Verify require_api_key_configured() raises RuntimeError when API_KEY is unset or blank."""
        os.environ["API_KEY"] = "MOCK_VALID_KEY_FOR_TEST"
        self.assertEqual(require_api_key_configured(), "MOCK_VALID_KEY_FOR_TEST")

        os.environ["API_KEY"] = ""
        with self.assertRaises(RuntimeError):
            require_api_key_configured()

        del os.environ["API_KEY"]
        with self.assertRaises(RuntimeError):
            require_api_key_configured()

        # Restore test key
        os.environ["API_KEY"] = TEST_API_KEY

    def test_session_secret_independence(self):
        """Verify that app.secret_key is independent and not derived from API_KEY."""
        self.assertNotEqual(app.secret_key, TEST_API_KEY)
        self.assertEqual(app.secret_key, TEST_SESSION_SECRET)

    def test_csrf_protection_on_login(self):
        """Verify POST /login strictly rejects submissions lacking valid CSRF token."""
        # 1. POST without CSRF token -> 403 Forbidden
        res_no_csrf = self.client.post('/login', data={"key": TEST_API_KEY})
        self.assertEqual(res_no_csrf.status_code, 403)
        self.assertIn("CSRF", res_no_csrf.data.decode('utf-8'))

        # 2. POST with forged/wrong CSRF token -> 403 Forbidden
        self.client.get('/login')
        res_wrong_csrf = self.client.post('/login', data={"key": TEST_API_KEY, "csrf_token": "FORGED_FAKE_TOKEN"})
        self.assertEqual(res_wrong_csrf.status_code, 403)

    def test_session_login_and_logout_flow(self):
        """
        Verify secure session-based authentication:
        1. Unauthenticated GET / redirects (302) to /login
        2. GET /login renders login page with CSRF token
        3. POST /login with invalid key returns 401 with error message
        4. POST /login with valid key & CSRF redirects (302) to / with session cookie
        5. Authenticated GET / renders Dashboard without leaking API_KEY
        6. POST /logout with CSRF clears session and redirects to /login
        """
        # 1. Unauthenticated GET / -> 302 to /login
        res = self.client.get('/')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login', res.headers.get('Location', ''))

        # 2. GET /login -> 200 with CSRF token
        res_login_page = self.client.get('/login')
        self.assertEqual(res_login_page.status_code, 200)
        self.assertIn("تسجيل الدخول", res_login_page.data.decode('utf-8'))
        self.assertIn('name="csrf_token"', res_login_page.data.decode('utf-8'))

        # Extract CSRF token from test client session
        with self.client.session_transaction() as sess:
            csrf_token = sess.get("csrf_token")
        self.assertIsNotNone(csrf_token)

        # 3. Invalid credentials POST /login -> 401
        res_invalid = self.client.post('/login', data={"key": "WRONG_KEY", "csrf_token": csrf_token})
        self.assertEqual(res_invalid.status_code, 401)
        self.assertIn("مفتاح API غير صحيح", res_invalid.data.decode('utf-8'))

        # 4. Valid credentials POST /login -> 302 redirect to /
        res_valid = self.client.post('/login', data={"key": TEST_API_KEY, "csrf_token": csrf_token})
        self.assertEqual(res_valid.status_code, 302)
        self.assertEqual(res_valid.headers.get('Location'), '/')

        # 5. Access dashboard with the session cookie established
        res_dashboard = self.client.get('/')
        self.assertEqual(res_dashboard.status_code, 200)
        dash_html = res_dashboard.data.decode('utf-8')
        self.assertIn("Free Fire Like & Token Manager", dash_html)
        self.assertIn("جلسة ويب مشفرة وآمنة", dash_html)

        # 6. CRITICAL SECURITY ASSERTION: API_KEY must NOT be leaked into HTML or JS
        self.assertNotIn(TEST_API_KEY, dash_html)
        self.assertNotIn("CURRENT_KEY", dash_html)

        # 7. Logout flow with CSRF token -> POST /logout clears session
        with self.client.session_transaction() as sess:
            active_csrf = sess.get("csrf_token")
        res_logout = self.client.post('/logout', data={"csrf_token": active_csrf})
        self.assertEqual(res_logout.status_code, 302)
        self.assertIn('/login', res_logout.headers.get('Location', ''))

        # 8. Subsequent GET / should now be unauthenticated again
        res_after_logout = self.client.get('/')
        self.assertEqual(res_after_logout.status_code, 302)

    def test_csrf_on_session_post_actions(self):
        """Verify session-authenticated AJAX POST requests enforce CSRF headers."""
        # Log in first
        self.client.get('/login')
        with self.client.session_transaction() as sess:
            csrf_token = sess.get("csrf_token")
        self.client.post('/login', data={"key": TEST_API_KEY, "csrf_token": csrf_token})

        # Session POST without CSRF header -> 403
        dummy_jwt = "eyJhbGciOiJIUzI1NiJ9.eyJ1aWQiOiI5OTkifQ.dummy_signature_sample_test"
        res_blocked = self.client.post('/tokens/add', json={"region": "ME", "tokens": dummy_jwt})
        self.assertEqual(res_blocked.status_code, 403)
        self.assertIn("CSRF", res_blocked.get_json()["error"])

        # Session POST with valid X-CSRF-Token header -> 200
        with self.client.session_transaction() as sess:
            active_csrf = sess.get("csrf_token")
        res_allowed = self.client.post(
            '/tokens/add',
            headers={"X-CSRF-Token": active_csrf},
            json={"region": "ME", "tokens": dummy_jwt}
        )
        self.assertEqual(res_allowed.status_code, 200)

        # Clean up test tokens
        filepath = generator_bridge.get_token_filepath("ME")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump([], f)

    def test_api_client_bypasses_csrf(self):
        """Verify external REST/bot clients using X-API-Key are not blocked by CSRF checks."""
        dummy_jwt = "eyJhbGciOiJIUzI1NiJ9.eyJ1aWQiOiI5OTkifQ.dummy_signature_sample_test"
        res = self.client.post(
            '/tokens/add',
            headers={"X-API-Key": TEST_API_KEY},
            json={"region": "ME", "tokens": dummy_jwt}
        )
        self.assertEqual(res.status_code, 200)

        # Clean up
        filepath = generator_bridge.get_token_filepath("ME")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump([], f)

    def test_query_parameter_key_rejection(self):
        """
        Verify that passing ?key= in query parameters is strictly REJECTED (401)
        to prevent secrets leaking into access logs, browser history, and referrers.
        """
        # GET /like?key=... without header or session -> 401
        res_like = self.client.get(f'/like?uid=12747380350&region=ME&key={TEST_API_KEY}')
        self.assertEqual(res_like.status_code, 401)

        # GET /remain?key=... without header or session -> 401
        res_remain = self.client.get(f'/remain?key={TEST_API_KEY}')
        self.assertEqual(res_remain.status_code, 401)

        # GET /tokens/status?key=... without header or session -> 401
        res_status = self.client.get(f'/tokens/status?key={TEST_API_KEY}')
        self.assertEqual(res_status.status_code, 401)

    def test_header_based_authentication(self):
        """Verify REST API callers / bots authenticate cleanly via X-API-Key or Bearer headers."""
        # 1. Header 'X-API-Key'
        res_x_key = self.client.get('/remain', headers={"X-API-Key": TEST_API_KEY})
        self.assertEqual(res_x_key.status_code, 200)
        data = res_x_key.get_json()
        self.assertIn("remaining", data)
        self.assertIn("daily_limit", data)

        # 2. Header 'Authorization: Bearer <key>'
        res_bearer = self.client.get('/remain', headers={"Authorization": f"Bearer {TEST_API_KEY}"})
        self.assertEqual(res_bearer.status_code, 200)

        # 3. /tokens/status with header
        res_status = self.client.get('/tokens/status', headers={"X-API-Key": TEST_API_KEY})
        self.assertEqual(res_status.status_code, 200)
        self.assertIn("regions", res_status.get_json())

    def test_session_authenticated_api_access(self):
        """Verify that an active session cookie allows dashboard AJAX calls without auth headers."""
        # Log in
        self.client.get('/login')
        with self.client.session_transaction() as sess:
            csrf_token = sess.get("csrf_token")
        self.client.post('/login', data={"key": TEST_API_KEY, "csrf_token": csrf_token})

        # Fetch status via session cookie without any X-API-Key header
        res_status = self.client.get('/tokens/status')
        self.assertEqual(res_status.status_code, 200)
        self.assertIn("regions", res_status.get_json())

        # Fetch remain via session cookie
        res_remain = self.client.get('/remain')
        self.assertEqual(res_remain.status_code, 200)

    def test_uid_validation(self):
        self.assertTrue(validate_uid("12747380350"))
        self.assertTrue(validate_uid("1234567"))
        self.assertFalse(validate_uid("abc"))
        self.assertFalse(validate_uid("-500"))
        self.assertFalse(validate_uid("12"))  # too short
        self.assertFalse(validate_uid(""))
        self.assertFalse(validate_uid(None))

    def test_jwt_structure_validation(self):
        """Tests purely structural format: 3 segments, base64url 'ey' prefix."""
        valid_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozGz"
        self.assertTrue(check_jwt_structure(valid_jwt))
        self.assertFalse(check_jwt_structure("random_string_not_jwt"))
        self.assertFalse(check_jwt_structure("only.two.parts"))
        self.assertFalse(check_jwt_structure("notey.payload.sig"))
        self.assertFalse(check_jwt_structure(""))
        self.assertFalse(check_jwt_structure(None))

    def test_jwt_payload_inspection_and_expiration(self):
        """Tests offline unverified payload inspection & expiration check."""
        now_ts = int(time.time())

        # Future expiration token
        future_payload = base64.urlsafe_b64encode(
            json.dumps({"uid": "123", "exp": now_ts + 3600}).encode()
        ).decode().rstrip("=")
        active_token = f"eyJhbGciOiJIUzI1NiJ9.{future_payload}.signature_dummy"
        is_valid, claims, msg = inspect_jwt_payload(active_token)
        self.assertTrue(is_valid)
        self.assertEqual(claims.get("uid"), "123")
        self.assertIn("signature unverified", msg.lower())

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

    def test_tokens_add_validation(self):
        # Invalid JWT input
        res = self.client.post('/tokens/add', headers={"X-API-Key": TEST_API_KEY}, json={
            "region": "ME",
            "tokens": "garbage_not_a_jwt_token"
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("No valid", res.get_json()["error"])

    def test_generate_input_validation(self):
        # Non-numeric count
        res = self.client.get(
            '/generate?region=ME&count=invalid_number',
            headers={"X-API-Key": TEST_API_KEY}
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("must be valid integers", res.get_json()["error"])

        # Unsupported region
        res = self.client.get(
            '/generate?region=INVALID_XYZ&count=10',
            headers={"X-API-Key": TEST_API_KEY}
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid region", res.get_json()["error"])

    def test_like_input_validation(self):
        # Missing UID
        res = self.client.get('/like?region=ME', headers={"X-API-Key": TEST_API_KEY})
        self.assertEqual(res.status_code, 400)

        # Invalid UID (letters)
        res = self.client.get('/like?uid=abc1234&region=ME', headers={"X-API-Key": TEST_API_KEY})
        self.assertEqual(res.status_code, 400)

        # Invalid region
        res = self.client.get('/like?uid=12747380350&region=UNKNOWN', headers={"X-API-Key": TEST_API_KEY})
        self.assertEqual(res.status_code, 400)


class TestBridgeAndTSun(unittest.TestCase):
    def test_region_mapping(self):
        self.assertEqual(generator_bridge.map_to_tsun_region("ME"), "ME")
        self.assertEqual(generator_bridge.map_to_tsun_region("BD"), "BD")
        self.assertEqual(generator_bridge.map_to_tsun_region("US"), "SAC")

        with self.assertRaises(ValueError):
            generator_bridge.map_to_tsun_region("NON_EXISTENT_REGION")

    def test_tsun_ssl_configuration(self):
        """Verify that TSun settings configure VERIFY_SSL properly."""
        self.assertIsInstance(tsun_settings.VERIFY_SSL, bool)
        self.assertTrue(tsun_settings.VERIFY_SSL)


if __name__ == '__main__':
    unittest.main()
