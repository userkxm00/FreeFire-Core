#CREDIT :- XHAMSTER.COM, @ARAFAT_FLEX, JONY SING
#ANY PROBLEM TG :- @ARAFAT_AHMED
from flask import Flask, request, jsonify, render_template_string, session, redirect
import asyncio
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import binascii
import aiohttp
import requests
import json
import base64
import time
import hashlib
import hmac
import secrets
import os
import threading
from datetime import datetime, date
import like_pb2
import uid_generator_pb2
import visit_count_pb2
from google.protobuf.message import DecodeError
from collections import OrderedDict

# 📄 Load local .env file if present (safe fallback without third-party dependencies)
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    try:
        with open(_env_path, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    _k, _v = _k.strip(), _v.strip().strip('"').strip("'")
                    if _k and _k not in os.environ:
                        os.environ[_k] = _v
    except Exception:
        pass

import generator_bridge

app = Flask(__name__)

# 🔐 Security: Require explicit API_KEY configuration. No default hardcoded key.
def require_api_key_configured():
    """
    Ensure API_KEY is set in environment.
    Executed at application startup across all environments (Vercel, WSGI, local).
    Raises RuntimeError if missing or empty.
    """
    key = os.getenv("API_KEY")
    if not key or not str(key).strip():
        raise RuntimeError(
            "CRITICAL SECURITY CONFIGURATION ERROR: Environment variable 'API_KEY' is not set! "
            "FreeFire-Core refuses to start with an insecure or missing key. "
            "Please configure API_KEY in your environment or .env file before running."
        )
    return str(key).strip()

# Enforce immediately upon module import/initialization (covers direct run, WSGI, and Vercel)
API_KEY = require_api_key_configured()

# 🔐 Session Configuration for Secure Dashboard Authentication (HttpOnly, SameSite, Secure)
SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET or not str(SESSION_SECRET).strip():
    # Cryptographically secure independent random secret (never derived from API_KEY)
    SESSION_SECRET = secrets.token_hex(32)
    app.logger.warning(
        "SESSION_SECRET is not configured in environment. Generated an ephemeral in-memory secret. "
        "Set SESSION_SECRET in .env or environment variables for persistent sessions across restarts."
    )
app.secret_key = SESSION_SECRET
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Auto-detect HTTPS/Production or explicit COOKIE_SECURE
_is_production = (
    os.getenv("VERCEL") == "1"
    or os.getenv("ENV", "").lower() == "production"
    or os.getenv("FLASK_ENV", "").lower() == "production"
)
_cookie_secure_env = os.getenv("COOKIE_SECURE")
if _cookie_secure_env is not None:
    app.config["SESSION_COOKIE_SECURE"] = _cookie_secure_env.lower() in ("1", "true", "yes")
else:
    app.config["SESSION_COOKIE_SECURE"] = _is_production

# ☁️ Vercel Architecture Warning
if os.getenv("VERCEL") == "1":
    app.logger.warning(
        "FreeFire-Core is executing in Vercel serverless environment. "
        "Local filesystem writes (usage_state.json, token_*.json) are ephemeral and do not persist across requests. "
        "For persistent production deployment, an external database (such as Upstash Redis or Supabase) must be configured."
    )

# 🌐 Configurable SSL verification (enabled by default for security)
VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() in {"1", "true", "yes"}

# ⚙️ Auto-refill configuration
AUTO_REFILL_ENABLED = os.getenv("AUTO_REFILL", "true").lower() in {"1", "true", "yes"}
MIN_TOKEN_THRESHOLD = int(os.getenv("MIN_TOKEN_THRESHOLD", "5"))
DEFAULT_REFILL_AMOUNT = int(os.getenv("DEFAULT_REFILL_AMOUNT", "10"))

# Allowed regions list
ALLOWED_REGIONS = {
    "BD", "IND", "BR", "US", "SAC", "NA", "ME", "ID", "VN", "TH", "PK", "CIS", "SG", "TW"
}

# 🔢 Persistent Thread-Safe Usage Tracker
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usage_state.json")
_STATE_LOCK = threading.Lock()
daily_limit = 30


class UsageTracker:
    """
    Thread-safe, process-level daily usage tracker with atomic file writes.
    Note: For distributed multi-instance or serverless deployments (Vercel, AWS Lambda),
    an external state store such as Redis or a database should be used.
    """
    @staticmethod
    def _load_state():
        today_str = str(date.today())
        if not os.path.exists(STATE_FILE):
            return 0
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and data.get("date") == today_str:
                    return int(data.get("used_count", 0))
                return 0
        except (json.JSONDecodeError, IOError, ValueError) as exc:
            app.logger.warning(f"Error reading usage state file ({exc}), returning 0.")
            return 0

    @staticmethod
    def _save_state(count):
        today_str = str(date.today())
        tmp_file = STATE_FILE + f".tmp_{os.getpid()}_{threading.get_ident()}"
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump({"date": today_str, "used_count": count}, f)
            os.replace(tmp_file, STATE_FILE)
        except (IOError, OSError) as exc:
            app.logger.error(f"Failed to atomically persist usage state: {exc}")
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except OSError:
                    pass

    @classmethod
    def get_used_count(cls):
        with _STATE_LOCK:
            return cls._load_state()

    @classmethod
    def increment(cls):
        with _STATE_LOCK:
            count = cls._load_state() + 1
            cls._save_state(count)
            return count


def is_request_authenticated(provided_key=None):
    """
    Multi-channel secure authentication:
    1. Active Flask session cookie (session['authenticated'] == True) - used by Web UI
    2. Header 'X-API-Key' - used by REST clients / bots
    3. Header 'Authorization: Bearer <key>' - standard REST Bearer auth
    4. JSON body 'key' (POST requests only)

    SECURITY ENFORCEMENT:
    Query parameters (?key=...) are EXPLICITLY REJECTED to prevent API keys
    from leaking into browser history, server logs, reverse proxies, and referrer headers.
    """
    # 1. Session authentication (Web Dashboard)
    if session.get("authenticated") is True:
        return True

    expected = os.getenv("API_KEY")
    if not expected or not str(expected).strip():
        app.logger.warning("Rejecting request: API_KEY is not configured in environment.")
        return False

    key = provided_key
    if not key:
        key = request.headers.get("X-API-Key")
    if not key and request.headers.get("Authorization"):
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            key = auth[7:].strip()
    if not key and request.is_json and request.method == "POST":
        key = (request.get_json(silent=True) or {}).get("key")

    return key is not None and hmac.compare_digest(str(key).strip(), str(expected).strip())

# Backward-compatible alias
key_ok = is_request_authenticated


def get_or_create_csrf_token():
    """Ensure a cryptographically random CSRF token exists in the session and return it."""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]


def validate_csrf_token():
    """
    Validate CSRF token for state-modifying requests (POST, PUT, DELETE)
    made using browser session authentication.

    Requests authenticated with API Key headers (X-API-Key, Bearer) are immune to CSRF
    and do not require CSRF token validation.
    """
    # API clients authenticating via headers are immune to CSRF
    if request.headers.get("X-API-Key") or request.headers.get("Authorization"):
        return True

    # Browser sessions: enforce CSRF validation
    if session.get("authenticated") is True:
        token = (
            request.headers.get("X-CSRF-Token")
            or request.form.get("csrf_token")
            or (request.get_json(silent=True) or {}).get("csrf_token")
        )
        session_token = session.get("csrf_token")
        if not token or not session_token or not hmac.compare_digest(str(token), str(session_token)):
            return False
        return True

    return True


def validate_uid(uid_str):
    """Ensure UID is a positive integer between 7 and 15 digits."""
    if not uid_str or not str(uid_str).strip().isdigit():
        return False
    val = int(uid_str)
    return 100_000 <= val <= 999_999_999_999_999


def check_jwt_structure(token_str):
    """
    Syntax check: Verify that token consists of 3 dot-separated segments,
    starts with base64url 'ey' (JSON '{'), and contains valid length.

    NOTE: This does NOT cryptographically verify Garena's signature
    as Garena's private/public keys are proprietary.
    """
    if not token_str or not isinstance(token_str, str):
        return False
    parts = token_str.strip().split(".")
    return len(parts) == 3 and parts[0].startswith("ey") and len(token_str.strip()) > 20


def inspect_jwt_payload(token_str, allow_grace=False):
    """
    Offline Unverified Claims & Expiration Inspection.
    Decodes the JWT payload segment WITHOUT cryptographic signature verification.
    Checks the expiration timestamp ('exp') if present in claims.

    IMPORTANT DISTINCTION:
    A return of (True, ...) indicates structural validity and non-expired status ONLY.
    It does NOT prove that Garena issued or still recognizes the token. Cryptographic
    signature validation is impossible without Garena's signing keys.
    Returns (is_valid, claims, message).
    """
    if not check_jwt_structure(token_str):
        return False, {}, "Invalid JWT structure (must have 3 segments starting with ey)"

    parts = token_str.strip().split(".")
    payload_b64 = parts[1]
    padding = 4 - (len(payload_b64) % 4)
    if padding != 4:
        payload_b64 += "=" * padding

    try:
        decoded_bytes = base64.urlsafe_b64decode(payload_b64)
        claims = json.loads(decoded_bytes)
        exp = claims.get("exp")
        if exp is not None:
            now_ts = int(time.time())
            grace_seconds = int(os.getenv("TOKEN_EXPIRY_GRACE_SECONDS", "86400")) if allow_grace else 0
            if exp + grace_seconds < now_ts:
                return False, claims, f"Token expired at timestamp {exp} (now: {now_ts})"

        return True, claims, "Valid structure and non-expired (signature unverified)"
    except Exception as exc:
        return False, {}, f"Failed to decode JWT payload: {exc}"


def get_token_str(t):
    """Safely extract token string from either dict or str format."""
    if isinstance(t, dict):
        return t.get("token") or t.get("jwt_token") or ""
    elif isinstance(t, str):
        return t.strip()
    return ""


def load_tokens(region, auto_refill=True):
    """
    Load tokens for a region with optional automatic refill.
    Validates token structure and expiration before including.
    """
    try:
        current_count = generator_bridge.count_valid_tokens(region)

        if auto_refill and AUTO_REFILL_ENABLED and current_count < MIN_TOKEN_THRESHOLD:
            def _bg_refill():
                try:
                    generator_bridge.ensure_tokens_available(
                        region=region,
                        min_tokens=MIN_TOKEN_THRESHOLD,
                        refill_amount=DEFAULT_REFILL_AMOUNT,
                    )
                except Exception:
                    pass
            threading.Thread(target=_bg_refill, daemon=True).start()

        raw_tokens = generator_bridge.read_tokens(region)
        valid_tokens = []
        for t in raw_tokens:
            token_str = get_token_str(t)
            is_valid, _, _ = inspect_jwt_payload(token_str, allow_grace=True)
            if is_valid:
                if isinstance(t, dict):
                    t["token"] = token_str
                    t["jwt_token"] = token_str
                    valid_tokens.append(t)
                else:
                    valid_tokens.append({"token": token_str, "jwt_token": token_str})

        return valid_tokens if valid_tokens else None
    except Exception as e:
        app.logger.error(f"Error loading tokens for region {region}: {e}")
        return None


def encrypt_message(plaintext):
    try:
        key = b'Yg&tc%DEuh6%Zc^8'
        iv = b'6oyZDr22E3ychjM%'
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded_message = pad(plaintext, AES.block_size)
        encrypted_message = cipher.encrypt(padded_message)
        return binascii.hexlify(encrypted_message).decode('utf-8')
    except Exception as e:
        app.logger.error(f"Error encrypting message: {e}")
        return None


def create_protobuf_message(user_id, region):
    try:
        message = like_pb2.like()
        message.uid = int(user_id)
        message.region = region
        return message.SerializeToString()
    except Exception as e:
        app.logger.error(f"Error creating protobuf message: {e}")
        return None


async def send_request(session, encrypted_uid, token, url):
    try:
        edata = bytes.fromhex(encrypted_uid)
        headers = {
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Expect": "100-continue",
            "X-Unity-Version": "2018.4.11f1",
            "X-GA": "v1 1",
            "ReleaseVersion": "OB55"
        }
        async with session.post(url, data=edata, headers=headers) as response:
            return await response.text()
    except Exception as e:
        app.logger.error(f"Exception in send_request: {e}")
        return None


async def send_multiple_requests(uid, region, url):
    try:
        protobuf_message = create_protobuf_message(uid, region)
        if protobuf_message is None:
            return None
        encrypted_uid = encrypt_message(protobuf_message)
        if encrypted_uid is None:
            return None
        tokens = load_tokens(region, auto_refill=False)
        if tokens is None:
            return None
        token_list = [get_token_str(t) for t in tokens if get_token_str(t)]
        if not token_list:
            return None
        connector = aiohttp.TCPConnector(limit=100)
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = [send_request(session, encrypted_uid, tk, url) for tk in token_list]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        return results
    except Exception as e:
        app.logger.error(f"Exception in send_multiple_requests: {e}")
        return None


def create_protobuf(uid):
    try:
        message = uid_generator_pb2.uid_generator()
        message.saturn_ = int(uid)
        message.garena = 1
        return message.SerializeToString()
    except Exception as e:
        app.logger.error(f"Error creating uid protobuf: {e}")
        return None


def enc(uid):
    protobuf_data = create_protobuf(uid)
    if protobuf_data is None:
        return None
    return encrypt_message(protobuf_data)


def get_profile_url(region):
    if region == "IND":
        return "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
    elif region in {"BR", "US", "SAC", "NA"}:
        return "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
    else:
        return "https://clientbp.ppmainecoonghj.com/GetPlayerPersonalShow"


def get_like_url(region):
    if region == "IND":
        return "https://client.ind.freefiremobile.com/LikeProfile"
    elif region in {"BR", "US", "SAC", "NA"}:
        return "https://client.us.freefiremobile.com/LikeProfile"
    else:
        return "https://clientbp.ppmainecoonghj.com/LikeProfile"


def make_request(encrypt, region, token):
    try:
        url = get_profile_url(region)
        edata = bytes.fromhex(encrypt)
        headers = {
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Expect": "100-continue",
            "X-Unity-Version": "2018.4.11f1",
            "X-GA": "v1 1",
            "ReleaseVersion": "OB55"
        }
        response = requests.post(url, data=edata, headers=headers, verify=VERIFY_SSL, timeout=10)
        binary = response.content
        decoded = visit_count_pb2.Info()
        decoded.ParseFromString(binary)
        return decoded
    except DecodeError as e:
        app.logger.error(f"DecodeError: {e}")
        return None
    except Exception as e:
        app.logger.error(f"Error in make_request: {e}")
        return None


# 🔒 HTML Login Gate (Returned with 401 or 200 on /login)
LOGIN_GATE_HTML = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>تسجيل الدخول - FreeFire Core</title>
    <style>
        body {
            background-color: #0d1117;
            color: #c9d1d9;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100vh;
            margin: 0;
            direction: rtl;
        }
        .login-box {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 30px;
            max-width: 420px;
            width: 90%;
            text-align: center;
            box-shadow: 0 8px 24px rgba(0,0,0,0.5);
        }
        h2 { color: #ff5722; margin-bottom: 12px; font-size: 1.5rem; }
        p { color: #8b949e; font-size: 0.9rem; margin-bottom: 20px; }
        input {
            width: 100%;
            padding: 12px;
            background: #090d13;
            border: 1px solid #30363d;
            border-radius: 6px;
            color: #f0f6fc;
            font-size: 1rem;
            margin-bottom: 16px;
            box-sizing: border-box;
            text-align: center;
        }
        button {
            width: 100%;
            padding: 12px;
            background: #ff5722;
            border: none;
            border-radius: 6px;
            color: #fff;
            font-size: 1rem;
            font-weight: bold;
            cursor: pointer;
        }
        button:hover { background: #f4511e; }
        .alert {
            background: #3c1e1e;
            color: #f85149;
            border: 1px solid #da3633;
            padding: 10px;
            border-radius: 6px;
            font-size: 0.85rem;
            margin-bottom: 15px;
        }
        .badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            background: #21262d;
            color: #58a6ff;
            font-size: 0.8rem;
            margin-bottom: 15px;
        }
    </style>
</head>
<body>
    <div class="login-box">
        <h2>🔒 تسجيل الدخول للوحة التحكم</h2>
        <span class="badge">جلسة مشفرة آمنة (POST Auth)</span>
        {% if error %}
        <div class="alert">{{ error }}</div>
        {% else %}
        <p>أدخل مفتاح الـ API للوصول. يتم الإرسال عبر طلب POST مشفر دون تسريب المفتاح في الروابط.</p>
        {% endif %}
        <form method="POST" action="/login">
            <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
            <input type="password" name="key" placeholder="أدخل مفتاح الـ API هنا..." required autofocus>
            <button type="submit">فتح لوحة التحكم</button>
        </form>
    </div>
</body>
</html>"""

# 🏠 Web UI Dashboard at / (Only rendered when authenticated)
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="csrf-token" content="{{ csrf_token }}">
    <title>Free Fire Like & Token Manager - ARAFAT FLEX</title>
    <style>
        :root {
            --bg: #0d1117;
            --card-bg: #161b22;
            --border: #30363d;
            --primary: #ff5722;
            --primary-hover: #f4511e;
            --text: #c9d1d9;
            --text-heading: #f0f6fc;
            --success: #2ea043;
            --danger: #da3633;
            --font: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background-color: var(--bg);
            color: var(--text);
            font-family: var(--font);
            padding: 20px;
            direction: rtl;
        }
        .container { max-width: 1000px; margin: 0 auto; }
        header {
            text-align: center;
            padding: 25px 0;
            border-bottom: 2px solid var(--border);
            margin-bottom: 25px;
        }
        header h1 {
            color: var(--primary);
            font-size: 2.2rem;
            margin-bottom: 8px;
        }
        header p { color: #8b949e; }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 20px;
            margin-bottom: 25px;
        }
        .card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 22px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.4);
        }
        .card h2 {
            color: var(--text-heading);
            font-size: 1.3rem;
            margin-bottom: 15px;
            border-bottom: 1px solid var(--border);
            padding-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        label {
            display: block;
            margin-top: 12px;
            margin-bottom: 5px;
            font-size: 0.9rem;
            color: #8b949e;
        }
        input, select, textarea {
            width: 100%;
            padding: 10px 12px;
            background: #090d13;
            border: 1px solid var(--border);
            border-radius: 6px;
            color: var(--text-heading);
            font-size: 0.95rem;
        }
        input:focus, select:focus, textarea:focus {
            outline: none;
            border-color: var(--primary);
        }
        button {
            width: 100%;
            margin-top: 18px;
            padding: 12px;
            background: var(--primary);
            border: none;
            border-radius: 6px;
            color: #fff;
            font-size: 1rem;
            font-weight: bold;
            cursor: pointer;
            transition: 0.2s;
        }
        button:hover { background: var(--primary-hover); }
        .btn-green { background: var(--success); }
        .btn-green:hover { background: #2c974b; }
        .result-box {
            margin-top: 15px;
            padding: 12px;
            border-radius: 6px;
            background: #090d13;
            border: 1px solid var(--border);
            display: none;
            font-size: 0.9rem;
            white-space: pre-wrap;
            direction: ltr;
            text-align: left;
        }
        .stats-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }
        .stats-table th, .stats-table td {
            padding: 8px 12px;
            border: 1px solid var(--border);
            text-align: center;
            font-size: 0.88rem;
        }
        .stats-table th { background: #1f242c; color: var(--primary); }
        .badge {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 0.8rem;
            background: #21262d;
            color: #58a6ff;
        }
        .badge-green { background: #193623; color: #3fb950; }
        .badge-red { background: #3c1e1e; color: #f85149; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px; flex-wrap:wrap; gap:10px;">
                <span class="badge badge-green">🔒 جلسة ويب مشفرة وآمنة (HttpOnly Cookie)</span>
                <form method="POST" action="/logout" style="margin:0;">
                    <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
                    <button type="submit" style="background:#21262d; border:1px solid #30363d; color:#c9d1d9; padding:6px 14px; border-radius:6px; cursor:pointer; font-size:0.85rem; width:auto; margin:0;">تسجيل الخروج 🚪</button>
                </form>
            </div>
            <h1>🔥 ARAFAT FLEX - FREE FIRE LIKE BOT</h1>
            <p>نظام زيادة لايكات فري فاير وإدارة التوكنات المتكامل</p>
        </header>

        <div class="grid">
            <!-- Card 1: إرسال لايكات -->
            <div class="card">
                <h2>🚀 إرسال اللايكات للاعب</h2>
                <label>معرف اللاعب (Player UID):</label>
                <input type="number" id="like_uid" placeholder="مثال: 12747380350" value="12747380350">

                <label>السيرفر (Region):</label>
                <select id="like_region">
                    <option value="ME" selected>الشرق الأوسط (ME)</option>
                    <option value="BD">بنغلاديش (BD)</option>
                    <option value="IND">الهند (IND)</option>
                    <option value="BR">البرازيل (BR)</option>
                    <option value="SAC">أمريكا الجنوبية (SAC / NA / US)</option>
                    <option value="ID">إندونيسيا (ID)</option>
                    <option value="VN">فيتنام (VN)</option>
                    <option value="TH">تايلاند (TH)</option>
                    <option value="PK">باكستان (PK)</option>
                    <option value="CIS">روسيا / CIS</option>
                </select>

                <button id="like_btn" onclick="sendLikes()">إرسال اللايكات الآن</button>
                <div id="like_result" class="result-box"></div>
            </div>

            <!-- Card 2: إضافة توكنات -->
            <div class="card">
                <h2>🔑 إضافة توكنات مباشرة</h2>
                <p style="font-size:0.85rem; color:#8b949e;">الصق توكنات JWT الصالحة هنا (توكن واحد في كل سطر أو بصيغة JSON):</p>
                <label>السيرفر المستهدف:</label>
                <select id="token_region">
                    <option value="ME" selected>الشرق الأوسط (ME)</option>
                    <option value="BD">بنغلاديش (BD)</option>
                    <option value="IND">الهند (IND)</option>
                    <option value="BR">البرازيل (BR)</option>
                    <option value="SAC">أمريكا (SAC)</option>
                    <option value="ID">إندونيسيا (ID)</option>
                    <option value="VN">فيتنام (VN)</option>
                    <option value="PK">باكستان (PK)</option>
                    <option value="CIS">CIS</option>
                </select>

                <label>نص التوكنات (JWT Tokens):</label>
                <textarea id="tokens_text" rows="5" placeholder="eyJhbGciOi...&#10;eyJhbGciOi..."></textarea>

                <button class="btn-green" onclick="addTokens()">💾 حفظ التوكنات للسيرفر</button>
                <div id="token_add_result" class="result-box"></div>
            </div>
        </div>

        <div class="grid">
            <!-- Card 3: مولد الحسابات -->
            <div class="card">
                <h2>⚡ مولد التوكنات (TSun Engine)</h2>
                <label>السيرفر:</label>
                <select id="gen_region">
                    <option value="BD" selected>بنغلاديش (BD)</option>
                    <option value="ME">الشرق الأوسط (ME)</option>
                    <option value="IND">الهند (IND)</option>
                    <option value="BR">البرازيل (BR)</option>
                    <option value="ID">إندونيسيا (ID)</option>
                    <option value="PK">باكستان (PK)</option>
                </select>

                <label>عدد الحسابات:</label>
                <input type="number" id="gen_count" value="10" min="1" max="50">

                <button onclick="generateTokens()">توليد التوكنات الآن</button>
                <div id="gen_result" class="result-box"></div>
            </div>

            <!-- Card 4: إحصائيات التوكنات -->
            <div class="card">
                <h2>📊 رصيد التوكنات والحصة اليومية</h2>
                <p style="font-size:0.9rem; margin-bottom:8px;">
                    الحصة اليومية المتبقية: <span class="badge badge-green" id="remain_stat">--</span>
                </p>
                <table class="stats-table" id="tokens_table">
                    <thead>
                        <tr>
                            <th>السيرفر</th>
                            <th>التوكنات المتوفرة</th>
                            <th>الملف</th>
                        </tr>
                    </thead>
                    <tbody id="tokens_tbody">
                        <tr><td colspan="3">جاري التحميل...</td></tr>
                    </tbody>
                </table>
                <button style="margin-top:10px; background:#21262d;" onclick="loadStats()">🔄 تحديث الإحصائيات</button>
            </div>
        </div>
    </div>

    <script>
        // Secure Session Auth: Browser transmits HttpOnly session cookies automatically.
        // No API keys are embedded or accessible in JavaScript or HTML.
        const CSRF_TOKEN = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';

        async function loadStats() {
            try {
                const res = await fetch('/tokens/status');
                const data = await res.json();
                const tbody = document.getElementById('tokens_tbody');
                tbody.innerHTML = '';
                if (data.regions) {
                    for (const [reg, info] of Object.entries(data.regions)) {
                        const tr = document.createElement('tr');
                        const badgeClass = info.valid_tokens > 0 ? 'badge-green' : 'badge-red';
                        tr.innerHTML = `<td><b>${reg}</b></td><td><span class="badge ${badgeClass}">${info.valid_tokens}</span></td><td><code>${info.file}</code></td>`;
                        tbody.appendChild(tr);
                    }
                }

                const remainRes = await fetch('/remain');
                if (remainRes.ok) {
                    const remainData = await remainRes.json();
                    document.getElementById('remain_stat').innerText = `${remainData.remaining} / ${remainData.daily_limit} (مستخدم: ${remainData.used})`;
                }
            } catch (e) {
                console.error(e);
            }
        }

        async function sendLikes() {
            const uid = document.getElementById('like_uid').value.trim();
            const region = document.getElementById('like_region').value;
            const btn = document.getElementById('like_btn');
            const resBox = document.getElementById('like_result');

            if (!uid) { alert('يرجى إدخال UID اللاعب!'); return; }

            btn.disabled = true;
            btn.innerText = 'جاري إرسال الطلب... ⏳';
            resBox.style.display = 'block';
            resBox.innerText = 'جاري الاتصال بسيرفر فري فاير...';

            try {
                const response = await fetch(`/like?uid=${encodeURIComponent(uid)}&region=${encodeURIComponent(region)}`);
                const json = await response.json();
                resBox.innerText = JSON.stringify(json, null, 2);
                loadStats();
            } catch (e) {
                resBox.innerText = 'خطأ في الاتصال: ' + e;
            } finally {
                btn.disabled = false;
                btn.innerText = 'إرسال اللايكات الآن';
            }
        }

        async function addTokens() {
            const region = document.getElementById('token_region').value;
            const text = document.getElementById('tokens_text').value.trim();
            const resBox = document.getElementById('token_add_result');

            if (!text) { alert('يرجى لصق التوكنات أولاً!'); return; }
            resBox.style.display = 'block';
            resBox.innerText = 'جاري حفظ التوكنات...';

            try {
                const response = await fetch('/tokens/add', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRF-Token': CSRF_TOKEN
                    },
                    body: JSON.stringify({region: region, tokens: text})
                });
                const json = await response.json();
                resBox.innerText = JSON.stringify(json, null, 2);
                document.getElementById('tokens_text').value = '';
                loadStats();
            } catch (e) {
                resBox.innerText = 'خطأ: ' + e;
            }
        }

        async function generateTokens() {
            const region = document.getElementById('gen_region').value;
            const count = document.getElementById('gen_count').value;
            const resBox = document.getElementById('gen_result');

            resBox.style.display = 'block';
            resBox.innerText = 'جاري التوليد... قد يستغرق بضع ثوانٍ...';

            try {
                const response = await fetch(`/generate?region=${encodeURIComponent(region)}&count=${encodeURIComponent(count)}`, {
                    headers: {
                        'X-CSRF-Token': CSRF_TOKEN
                    }
                });
                const json = await response.json();
                resBox.innerText = JSON.stringify(json, null, 2);
                loadStats();
            } catch (e) {
                resBox.innerText = 'خطأ: ' + e;
            }
        }

        window.onload = loadStats;
    </script>
</body>
</html>"""


# 🔐 Authentication & Session Routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        if session.get("authenticated") is True:
            return redirect('/')
        csrf = get_or_create_csrf_token()
        return render_template_string(LOGIN_GATE_HTML, error=None, csrf_token=csrf), 200

    # POST: enforce CSRF protection
    csrf_provided = request.form.get("csrf_token") or (request.get_json(silent=True) or {}).get("csrf_token")
    csrf_expected = session.get("csrf_token")
    if not csrf_provided or not csrf_expected or not hmac.compare_digest(str(csrf_provided), str(csrf_expected)):
        return render_template_string(
            LOGIN_GATE_HTML,
            error="رمز CSRF غير صالح أو منتهي الصلاحية. يرجى إعادة تحميل الصفحة والمحاولة مجدداً.",
            csrf_token=get_or_create_csrf_token()
        ), 403

    # receive API key in body, NEVER in query params or URLs
    provided_key = request.form.get("key")
    if not provided_key and request.is_json:
        provided_key = (request.get_json(silent=True) or {}).get("key")

    expected = os.getenv("API_KEY")
    if expected and provided_key and hmac.compare_digest(str(provided_key).strip(), str(expected).strip()):
        session["authenticated"] = True
        get_or_create_csrf_token()
        return redirect('/')

    return render_template_string(
        LOGIN_GATE_HTML,
        error="مفتاح API غير صحيح أو غير مصرح به. يرجى التأكد من المفتاح والمحاولة مرة أخرى.",
        csrf_token=get_or_create_csrf_token()
    ), 401


@app.route('/logout', methods=['GET', 'POST'])
def logout():
    # Enforce CSRF protection on logout if user was authenticated
    if session.get("authenticated") is True:
        csrf_provided = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        csrf_expected = session.get("csrf_token")
        if not csrf_provided or not csrf_expected or not hmac.compare_digest(str(csrf_provided), str(csrf_expected)):
            return {"error": "Invalid or missing CSRF token"}, 403

    session.clear()
    return redirect('/login')


# 🏠 Web UI Dashboard Route (Server-Side Session Check)
@app.route('/', methods=['GET'])
def home_dashboard():
    if not session.get("authenticated"):
        return redirect('/login')
    csrf = get_or_create_csrf_token()
    return render_template_string(DASHBOARD_HTML, csrf_token=csrf), 200


@app.route('/like', methods=['GET'])
def handle_requests():
    if not key_ok():
        return {"error": "Invalid or missing API key"}, 401

    uid = request.args.get("uid")
    region = request.args.get("region", "").upper().strip()

    # Strict input validation
    if not validate_uid(uid):
        return {"error": "UID must be a numeric ID between 7 and 15 digits"}, 400

    if not region or region not in ALLOWED_REGIONS:
        return {
            "error": f"Invalid region '{region}'. Allowed regions: {sorted(list(ALLOWED_REGIONS))}"
        }, 400

    try:
        def process_request():
            tokens = load_tokens(region, auto_refill=True)
            if not tokens:
                return {
                    "error": f"No valid tokens found for region '{region}'. Please paste tokens into the dashboard or add them to token_{region.lower()}.json.",
                    "region": region,
                    "tokens_available": 0,
                    "status": 2
                }, 400

            token = get_token_str(tokens[0])
            if not token:
                return {"error": "First token is invalid or empty.", "status": 2}, 400

            encrypted_uid = enc(uid)
            if encrypted_uid is None:
                return {"error": "Encryption of UID failed.", "status": 2}, 500

            before = make_request(encrypted_uid, region, token)
            if before is None:
                return {
                    "error": "Failed to get initial info from Free Fire server. Check if token is valid or server is in maintenance.",
                    "status": 2,
                    "region": region
                }, 400

            before_like = before.AccountInfo.Likes

            url = get_like_url(region)
            asyncio.run(send_multiple_requests(uid, region, url))

            after = make_request(encrypted_uid, region, token)
            if after is None:
                return {"error": "Failed to get final info after sending likes.", "status": 2}, 500

            after_like = after.AccountInfo.Likes
            like_given = after_like - before_like
            status = 1 if like_given > 0 else 2

            used_count = UsageTracker.get_used_count()
            if status == 1:
                used_count = UsageTracker.increment()

            remaining = max(daily_limit - used_count, 0)

            result = OrderedDict([
                ("LikesGivenByAPI", like_given),
                ("LikesafterCommand", after_like),
                ("LikesbeforeCommand", before_like),
                ("PlayerNickname", after.AccountInfo.PlayerNickname),
                ("Level", after.AccountInfo.Levels),
                ("Region", after.AccountInfo.PlayerRegion),
                ("UID", after.AccountInfo.UID),
                ("status", status),
                ("tokens_used", len(tokens)),
                ("daily_limit", daily_limit),
                ("used", used_count),
                ("remaining", remaining)
            ])

            return app.response_class(
                response=json.dumps(result, separators=(',', ':')),
                status=200,
                mimetype='application/json'
            )

        return process_request()

    except Exception as e:
        app.logger.error(f"Error in /like: {e}")
        return {"error": str(e)}, 500


# 🆕 /tokens/add endpoint (Add raw tokens directly with validation)
@app.route('/tokens/add', methods=['POST'])
def add_tokens_endpoint():
    if not key_ok():
        return {"error": "Invalid or missing API key"}, 401

    if not validate_csrf_token():
        return {"error": "Invalid or missing CSRF token"}, 403

    data = request.get_json(silent=True) or {}
    region = (data.get("region") or request.args.get("region") or "BD").upper().strip()

    if region not in ALLOWED_REGIONS:
        return {"error": f"Invalid region '{region}'. Allowed: {sorted(list(ALLOWED_REGIONS))}"}, 400

    raw_input = data.get("tokens") or ""
    entries_to_add = []
    rejected_count = 0

    def _process_candidate(candidate_str):
        nonlocal rejected_count
        candidate_str = candidate_str.strip().strip('"').strip("'").strip(',')
        is_valid, claims, _ = inspect_jwt_payload(candidate_str)
        if is_valid:
            entries_to_add.append({
                "token": candidate_str,
                "jwt_token": candidate_str,
                "account_id": claims.get("account_id") or claims.get("external_id") or "",
                "region": region,
                "date_added": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
        elif candidate_str:
            rejected_count += 1

    if isinstance(raw_input, str):
        raw_input = raw_input.strip()
        if raw_input.startswith("[") and raw_input.endswith("]"):
            try:
                parsed = json.loads(raw_input)
                if isinstance(parsed, list):
                    for item in parsed:
                        _process_candidate(get_token_str(item))
            except Exception:
                pass
        if not entries_to_add:
            for line in raw_input.splitlines():
                _process_candidate(line)
    elif isinstance(raw_input, list):
        for item in raw_input:
            _process_candidate(get_token_str(item))

    if not entries_to_add:
        return {
            "error": "No valid non-expired JWT tokens found. Tokens must be 3-part base64url starting with 'ey' and have valid expiration."
        }, 400

    added = generator_bridge.append_tokens(region, entries_to_add)
    total = generator_bridge.count_valid_tokens(region)
    return jsonify({
        "status": "success",
        "region": region,
        "tokens_added": added,
        "tokens_rejected": rejected_count,
        "total_available": total
    }), 200


# 🆕 /generate endpoint (On-demand token generation via TSun)
@app.route('/generate', methods=['GET', 'POST'])
def generate_endpoint():
    if not key_ok():
        return {"error": "Invalid or missing API key"}, 401

    if request.method == 'POST' and not validate_csrf_token():
        return {"error": "Invalid or missing CSRF token"}, 403

    data = request.get_json(silent=True) or {}
    region = (request.args.get("region") or data.get("region") or "BD").upper().strip()

    if region not in ALLOWED_REGIONS:
        return {"error": f"Invalid region '{region}'. Allowed: {sorted(list(ALLOWED_REGIONS))}"}, 400

    # Safe numeric validation
    try:
        count = int(request.args.get("count") or data.get("count") or 10)
        threads = int(request.args.get("threads") or data.get("threads") or 3)
    except (ValueError, TypeError):
        return {"error": "'count' and 'threads' must be valid integers."}, 400

    count = max(1, min(count, 100))
    threads = max(1, min(threads, 8))
    is_async = (request.args.get("async") or str(data.get("async", ""))).lower() in {"1", "true", "yes"}

    name_prefix = request.args.get("name") or data.get("name") or "ARAFAT"
    pass_prefix = request.args.get("pass") or data.get("pass") or "Flex"

    if is_async:
        job_id = generator_bridge.start_background_generation(
            region=region,
            count=count,
            threads=threads,
            name_prefix=name_prefix,
            pass_prefix=pass_prefix,
        )
        return jsonify({
            "status": "queued",
            "job_id": job_id,
            "region": region,
            "target": count,
            "check_status_url": f"/generate/status?job_id={job_id}"
        }), 202

    result = generator_bridge.generate_tokens(
        region=region,
        count=count,
        threads=threads,
        name_prefix=name_prefix,
        pass_prefix=pass_prefix,
    )
    return jsonify(result), 200


# 🆕 /generate/status endpoint
@app.route('/generate/status', methods=['GET'])
def generate_status_endpoint():
    if not key_ok():
        return {"error": "Invalid or missing API key"}, 401

    job_id = request.args.get("job_id")
    if not job_id:
        return {"error": "job_id parameter is required"}, 400

    status = generator_bridge.get_job_status(job_id)
    if not status:
        return {"error": f"Job {job_id} not found"}, 404

    return jsonify(status), 200


# 🆕 /tokens/status endpoint
@app.route('/tokens/status', methods=['GET'])
def tokens_status_endpoint():
    if not key_ok():
        return {"error": "Invalid or missing API key"}, 401

    return jsonify(generator_bridge.get_tokens_status())


# 🆕 /remain endpoint
@app.route('/remain', methods=['GET'])
def remain_info():
    if not key_ok():
        return {"error": "Invalid or missing API key"}, 401

    used = UsageTracker.get_used_count()
    remaining = max(daily_limit - used, 0)
    data = {
        "daily_limit": daily_limit,
        "remaining": remaining,
        "used": used,
        "reset_info": "4:00 AM IST"
    }
    return jsonify(data)


if __name__ == '__main__':
    # Refuse to start without API_KEY set
    require_api_key_configured()
    app.run(debug=False, use_reloader=False)
