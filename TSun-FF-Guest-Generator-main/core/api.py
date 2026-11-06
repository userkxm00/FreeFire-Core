# Credits: TSun × Kittens
"""
core/api.py
~~~~~~~~~~~
All network calls to Garena and FreeFire endpoints:
  - Guest account registration
  - OAuth token grant
  - MajorRegister (in-game account setup)
  - MajorLogin (JWT extraction)
  - Region binding
Plus account/password generation helpers.
"""

from __future__ import annotations

import base64
import codecs
import hashlib
import hmac
import json
import random
import string
import time
from typing import Optional

import requests

import config.settings as settings
from core.crypto import aes_encrypt_hex, aes_encrypt_to_hex, build_proto_packet
from ui.display import print_success, print_warning


_REGISTER_URL = "https://100067.connect.garena.com/api/v2/oauth/guest:register"
_TOKEN_URL = "https://100067.connect.garena.com/api/v2/oauth/guest/token:grant"

# ── Name / Password generation ────────────────────────────────────────────────

_EXPONENT_MAP = {str(d): c for d, c in zip("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")}


def _generate_exponent_suffix() -> str:
    number = random.randint(1, 99_999)
    return "".join(_EXPONENT_MAP[d] for d in f"{number:05d}")


def generate_random_name(base_name: str) -> str:
    """Return *base_name* (up to 7 chars) with a unique exponent suffix."""
    return f"{base_name[:7]}{_generate_exponent_suffix()}"


def generate_custom_password(prefix: str) -> str:
    """Build a randomised password from *prefix* + random alphanumeric parts."""
    garena = base64.b64decode(settings.GARENA).decode("utf-8")
    chars  = string.ascii_uppercase + string.digits
    part1  = "".join(random.choice(chars) for _ in range(5))
    part2  = "".join(random.choice(chars) for _ in range(5))
    return f"{prefix}_{part1}_{garena}_{part2}"


# ── Delay ─────────────────────────────────────────────────────────────────────

def smart_delay(low: float = 1.0, high: float = 2.0) -> None:
    """Sleep for a random duration in [low, high] seconds."""
    time.sleep(random.uniform(low, high))


# ── Token encoding helpers ────────────────────────────────────────────────────

def _encode_open_id(original: str) -> dict[str, str]:
    keystream = [
        0x30, 0x30, 0x30, 0x32, 0x30, 0x31, 0x37, 0x30,
        0x30, 0x30, 0x30, 0x30, 0x32, 0x30, 0x31, 0x37,
        0x30, 0x30, 0x30, 0x30, 0x30, 0x32, 0x30, 0x31,
        0x37, 0x30, 0x30, 0x30, 0x30, 0x30, 0x32, 0x30,
    ]
    encoded = "".join(
        chr(ord(c) ^ keystream[i % len(keystream)]) for i, c in enumerate(original)
    )
    return {"open_id": original, "field_14": encoded}


def _to_unicode_escaped(s: str) -> str:
    return "".join(c if 32 <= ord(c) <= 126 else f"\\u{ord(c):04x}" for c in s)


# ── JWT decoding ──────────────────────────────────────────────────────────────

def decode_jwt_token(jwt_token: str) -> str:
    """Extract the account_id claim from a JWT token string."""
    try:
        parts = jwt_token.split(".")
        if len(parts) >= 2:
            payload = parts[1]
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += "=" * padding
            data = json.loads(base64.urlsafe_b64decode(payload))
            account_id = data.get("account_id") or data.get("external_id")
            if account_id:
                return str(account_id)
    except Exception as e:
        print_warning(f"JWT decode failed: {e}")
    return "N/A"


# ── API calls ─────────────────────────────────────────────────────────────────

def register_guest_account(region: str, password_prefix: str) -> Optional[dict]:
    """
    Step 1 — Register a new Garena guest account.
    Returns ``{"uid": ..., "password": ...}`` or None on failure.
    """
    if settings.EXIT_FLAG:
        return None
    try:
        password = generate_custom_password(password_prefix)
        payload = {
            "app_id": 100067,
            "client_type": 2,
            "password": password,
            "source": 2,
        }
        body_json = json.dumps(payload, separators=(",", ":"))
        signature = hmac.new(settings.KEY, body_json.encode("utf-8"), hashlib.sha256).hexdigest()

        headers_v2 = {
            "User-Agent": "GarenaMSDK/4.0.39(SM-A325M ;Android 13;en;HK;)",
            "Authorization": f"Signature {signature}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "Connection": "Keep-Alive",
            "Host": "100067.connect.garena.com",
        }

        # First attempt, then one retry for transient gateway/rate conditions.
        response = requests.post(
            _REGISTER_URL,
            headers=headers_v2,
            data=body_json,
            timeout=30,
            verify=settings.VERIFY_SSL,
        )
        for _ in range(1):
            if response.status_code not in (403, 429):
                break
            time.sleep(random.uniform(0.4, 1.0))
            response = requests.post(
                _REGISTER_URL,
                headers=headers_v2,
                data=body_json,
                timeout=30,
                verify=settings.VERIFY_SSL,
            )

        if response.status_code in (403, 429):
            print_warning(f"Guest register v2 blocked ({response.status_code}); skipping this attempt.")
            smart_delay()
            return None

        response.raise_for_status()
        body = response.json()
        data = body.get("data", body)

        # v2 format: {"code":0,"data":{"uid":...}}, legacy: {"uid":...}
        if (body.get("code", 0) == 0 and "uid" in data) or ("uid" in body):
            uid = data.get("uid") or body.get("uid")
            print_success(f"Guest account registered: {uid}")
            smart_delay()
            return {"uid": uid, "password": password}
        return None

    except Exception as e:
        print_warning(f"Guest registration failed: {e}")
        smart_delay()
        return None


def grant_oauth_token(uid: str, password: str) -> Optional[dict]:
    """
    Step 2 — Exchange uid/password for an OAuth access token.
    Returns ``{"open_id", "access_token", "refresh_token", "field"}`` or None.
    """
    if settings.EXIT_FLAG:
        return None
    try:
        client_secret = settings.KEY.decode("ascii")
        payload = {
            "client_id": 100067,
            "client_secret": client_secret,
            "client_type": 2,
            "password": password,
            "response_type": "token",
            "uid": uid,
        }
        body_json = json.dumps(payload, separators=(",", ":"))
        signature = hmac.new(settings.KEY, body_json.encode("utf-8"), hashlib.sha256).hexdigest()

        headers_v2 = {
            "User-Agent": "GarenaMSDK/4.0.39(SM-A325M ;Android 13;en;HK;)",
            "Authorization": f"Signature {signature}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "Connection": "Keep-Alive",
            "Host": "100067.connect.garena.com",
        }

        response = requests.post(
            _TOKEN_URL,
            headers=headers_v2,
            data=body_json,
            timeout=30,
            verify=settings.VERIFY_SSL,
        )
        for _ in range(1):
            if response.status_code not in (403, 429):
                break
            time.sleep(random.uniform(0.4, 1.0))
            response = requests.post(
                _TOKEN_URL,
                headers=headers_v2,
                data=body_json,
                timeout=30,
                verify=settings.VERIFY_SSL,
            )

        if response.status_code in (403, 429):
            print_warning(f"Token grant v2 blocked ({response.status_code}); skipping this attempt.")
            smart_delay()
            return None

        response.raise_for_status()
        body = response.json()
        data = body.get("data", body)
        if body.get("code", 0) == 0 and "open_id" in data:
            open_id      = data["open_id"]
            access_token = data["access_token"]
            result       = _encode_open_id(open_id)
            field_raw    = _to_unicode_escaped(result["field_14"])
            field        = codecs.decode(field_raw, "unicode_escape").encode("latin1")
            print_success(f"OAuth token granted for: {uid}")
            smart_delay()
            return {
                "open_id":       open_id,
                "access_token":  access_token,
                "refresh_token": data.get("refresh_token", ""),
                "field":         field,
            }
        return None

    except Exception as e:
        print_warning(f"Token grant failed: {e}")
        smart_delay()
        return None


def major_register(
    access_token: str,
    open_id: str,
    field: bytes,
    uid: str,
    password: str,
    account_name: str,
    region: str,
    is_ghost: bool = False,
) -> Optional[dict]:
    """
    Step 3 — Register the in-game account (MajorRegister) and perform login.
    Returns the full account_data dict or None on failure.
    """
    if settings.EXIT_FLAG:
        return None
    try:
        url  = "https://loginbp.ggblueshark.com/MajorRegister"
        host = "loginbp.ggblueshark.com"

        name      = generate_random_name(account_name)
        lang_code = "pt" if is_ghost else settings.REGION_LANG.get(region.upper(), "en")

        payload_fields = {
            1: name, 2: access_token, 3: open_id,
            5: 102000007, 6: 4, 7: 1, 13: 1,
            14: field, 15: lang_code, 16: 1, 17: 1,
        }
        proto_bytes       = build_proto_packet(payload_fields)
        encrypted_payload = aes_encrypt_hex(proto_bytes.hex())

        response = requests.post(
            url,
            headers={
                "Accept-Encoding": "gzip",
                "Authorization":   "Bearer",
                "Connection":      "Keep-Alive",
                "Content-Type":    "application/x-www-form-urlencoded",
                "Expect":          "100-continue",
                "Host":            host,
                "ReleaseVersion":  settings.RELEASE_VERSION,
                "User-Agent":      "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_I005DA Build/PI)",
                "X-GA":            "v1 1",
                "X-Unity-Version": "2018.4.",
            },
            data=encrypted_payload,
            verify=settings.VERIFY_SSL,
            timeout=30,
        )

        if response.status_code != 200:
            print_warning(f"MajorRegister returned {response.status_code}")
            return None

        print_success(f"MajorRegister successful: {name}")

        login_result = major_login(uid, password, access_token, open_id, region, is_ghost)
        account_id   = login_result.get("account_id", "N/A")
        jwt_token    = login_result.get("jwt_token", "")

        # Region binding (skip for ghost and BR)
        if not is_ghost and jwt_token and account_id != "N/A" and region.upper() != "BR":
            if bind_region(region, jwt_token):
                print_success(f"Region {region} bound successfully!")
            else:
                print_warning(f"Region binding failed for {region}")

        return {
            "uid":        uid,
            "password":   password,
            "name":       name,
            "region":     "GHOST" if is_ghost else region,
            "status":     "success",
            "account_id": account_id,
            "jwt_token":  jwt_token,
        }

    except Exception as e:
        print_warning(f"MajorRegister error: {e}")
        smart_delay()
        return None


# Hard-coded login payload template (binary protobuf blob)
_LOGIN_PAYLOAD_PARTS = [
    b'\x1a\x132025-08-30 05:19:21"\tfree fire(\x01:\x081.114.13B2Android OS 9 / API-28'
    b' (PI/rel.cjw.20220518.114133)J\x08HandheldR\nATM MobilsZ\x04WIFI`\xb6\nh\xee\x05'
    b'r\x03300z\x1fARMv7 VFPv3 NEON VMH | 2400 | 2\x80\x01\xc9\x0f\x8a\x01\x0fAdreno (TM) 640'
    b'\x92\x01\rOpenGL ES 3.2\x9a\x01+Google|dfa4ab4b-9dc4-454e-8065-e70c733fa53f'
    b'\xa2\x01\x0e105.235.139.91\xaa\x01\x02',
    None,  # placeholder for lang bytes
    b'\xb2\x01 1d8ec0240ede109973f3321b9354b44d\xba\x01\x014\xc2\x01\x08Handheld'
    b'\xca\x01\x10Asus ASUS_I005DA\xea\x01@afcfbf13334be42036e4f742c80b956344bed760'
    b'ac91b3aff9b607a610ab4390\xf0\x01\x01\xca\x02\nATM Mobils\xd2\x02\x04WIFI'
    b'\xca\x03 7428b253defc164018c604a1ebbfebdf\xe0\x03\xa8\x81\x02\xe8\x03\xf6\xe5\x01'
    b'\xf0\x03\xaf\x13\xf8\x03\x84\x07\x80\x04\xe7\xf0\x01\x88\x04\xa8\x81\x02'
    b'\x90\x04\xe7\xf0\x01\x98\x04\xa8\x81\x02\xc8\x04\x01\xd2\x04=/data/app/'
    b'com.dts.freefireth-PdeDnOilCSFn37p1AH_FLg==/lib/arm\xe0\x04\x01\xea\x04_'
    b'2087f61c19f57f2af4e7feff0b24d9d9|/data/app/com.dts.freefireth-PdeDnOilCSFn37p1AH_FLg=='
    b'/base.apk\xf0\x04\x03\xf8\x04\x01\x8a\x05\x0232\x9a\x05\n2019118692\xb2\x05'
    b'\tOpenGLES2\xb8\x05\xff\x7f\xc0\x05\x04\xe0\x05\xf3F\xea\x05\x07android'
    b'\xf2\x05pKqsHT5ZLWrYljNb5Vqh//yFRlaPHSO9NWSQsVvOmdhEEn7W+VHNUK+Q+fduA3pt'
    b'NrGB0Ll0LRz3WW0jOwesLj6aiU7sZ40p8BfUE/FI/jzSTwRe2\xf8\x05\xfb\xe4\x06'
    b'\x88\x06\x01\x90\x06\x01\x9a\x06\x014\xa2\x06\x014\xb2\x06"GQ@O\x00\x0e^'
    b'\x00D\x06UA\x0ePM\r\x13hZ\x07T\x06\x0cm\\V\x0ejYV;\x0bU5',
]

_ACCESS_TOKEN_PLACEHOLDER = b'afcfbf13334be42036e4f742c80b956344bed760ac91b3aff9b607a610ab4390'
_OPEN_ID_PLACEHOLDER      = b'1d8ec0240ede109973f3321b9354b44d'


def major_login(
    uid: str,
    password: str,
    access_token: str,
    open_id: str,
    region: str,
    is_ghost: bool = False,
) -> dict:
    """
    Perform MajorLogin and extract the JWT token + account_id.
    Returns ``{"account_id": ..., "jwt_token": ...}``.
    """
    try:
        lang = "pt" if is_ghost else settings.REGION_LANG.get(region.upper(), "en")

        parts = list(_LOGIN_PAYLOAD_PARTS)
        parts[1] = lang.encode("ascii")
        raw_payload = b"".join(parts)

        raw_payload = raw_payload.replace(_ACCESS_TOKEN_PLACEHOLDER, access_token.encode())
        raw_payload = raw_payload.replace(_OPEN_ID_PLACEHOLDER, open_id.encode())

        encrypted_hex = aes_encrypt_to_hex(raw_payload.hex())
        final_payload = bytes.fromhex(encrypted_hex)

        url  = "https://loginbp.ggblueshark.com/MajorLogin"
        host = "loginbp.ggblueshark.com"

        response = requests.post(
            url,
            headers={
                "Accept-Encoding": "gzip",
                "Authorization":   "Bearer",
                "Connection":      "Keep-Alive",
                "Content-Type":    "application/x-www-form-urlencoded",
                "Expect":          "100-continue",
                "Host":            host,
                "ReleaseVersion":  settings.RELEASE_VERSION,
                "User-Agent":      "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_I005DA Build/PI)",
                "X-GA":            "v1 1",
                "X-Unity-Version": "2018.4.11f1",
            },
            data=final_payload,
            verify=settings.VERIFY_SSL,
            timeout=30,
        )

        if response.status_code == 200 and len(response.text) > 10:
            jwt_start = response.text.find("eyJ")
            if jwt_start != -1:
                jwt_token  = response.text[jwt_start:]
                second_dot = jwt_token.find(".", jwt_token.find(".") + 1)
                if second_dot != -1:
                    jwt_token  = jwt_token[: second_dot + 44]
                    account_id = decode_jwt_token(jwt_token)
                    return {"account_id": account_id, "jwt_token": jwt_token}

        return {"account_id": "N/A", "jwt_token": ""}

    except Exception as e:
        print_warning(f"MajorLogin failed: {e}")
        return {"account_id": "N/A", "jwt_token": ""}


def bind_region(region: str, jwt_token: str) -> bool:
    """Force-bind an account to a specific region via ChooseRegion."""
    try:
        url = "https://loginbp.ggblueshark.com/ChooseRegion"

        region_code = "RU" if region.upper() == "CIS" else region.upper()
        proto_data  = build_proto_packet({1: region_code})
        payload     = bytes.fromhex(aes_encrypt_to_hex(proto_data.hex()))

        response = requests.post(
            url,
            data=payload,
            headers={
                "User-Agent":      "Dalvik/2.1.0 (Linux; U; Android 12; M2101K7AG Build/SKQ1.210908.001)",
                "Connection":      "Keep-Alive",
                "Accept-Encoding": "gzip",
                "Content-Type":    "application/x-www-form-urlencoded",
                "Expect":          "100-continue",
                "Authorization":   f"Bearer {jwt_token}",
                "X-Unity-Version": "2018.4.11f1",
                "X-GA":            "v1 1",
                "ReleaseVersion":  settings.RELEASE_VERSION,
            },
            verify=settings.VERIFY_SSL,
            timeout=30,
        )
        return response.status_code == 200

    except Exception as e:
        print_warning(f"Region binding failed: {e}")
        return False


# ── High-level account creation flow ─────────────────────────────────────────

def create_account(
    region: str,
    account_name: str,
    password_prefix: str,
    is_ghost: bool = False,
) -> Optional[dict]:
    """
    Full pipeline: register → token → MajorRegister → login → bind.
    Returns the final account_data dict or None.
    """
    if settings.EXIT_FLAG:
        return None

    # Step 1: Register guest account
    guest = register_guest_account(region, password_prefix)
    if not guest:
        return None
    uid, password = guest["uid"], guest["password"]

    # Step 2: OAuth token grant
    oauth = grant_oauth_token(uid, password)
    if not oauth:
        return None

    # Step 3: MajorRegister + login + region bind
    return major_register(
        access_token=oauth["access_token"],
        open_id=oauth["open_id"],
        field=oauth["field"],
        uid=uid,
        password=password,
        account_name=account_name,
        region=region,
        is_ghost=is_ghost,
    )
