#CREDIT :- XHAMSTER.COM, @ARAFAT_FLEX, JONY SING
#ANY PROBLEM TG :- @ARAFAT_AHMED
from flask import Flask, request, jsonify, render_template_string
import asyncio
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import binascii
import aiohttp
import requests
import json
import like_pb2
import uid_generator_pb2
import visit_count_pb2
from google.protobuf.message import DecodeError
from collections import OrderedDict
import hmac
import os
import generator_bridge

app = Flask(__name__)

# 🔢 Like limit tracking
daily_limit = 30
used_count = 0

# 🔑 API key (use ?key=@ARAFAT_FLEX)
API_KEY = os.getenv("API_KEY", "@ARAFAT_FLEX")

# ⚙️ Auto-refill configuration
AUTO_REFILL_ENABLED = os.getenv("AUTO_REFILL", "true").lower() in {"1", "true", "yes"}
MIN_TOKEN_THRESHOLD = int(os.getenv("MIN_TOKEN_THRESHOLD", "5"))
DEFAULT_REFILL_AMOUNT = int(os.getenv("DEFAULT_REFILL_AMOUNT", "10"))


def key_ok(provided):
    return provided is not None and hmac.compare_digest(str(provided), API_KEY)


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
    Supports token, jwt_token, and plain string formats.
    """
    try:
        current_count = generator_bridge.count_valid_tokens(region)

        if auto_refill and AUTO_REFILL_ENABLED and current_count < MIN_TOKEN_THRESHOLD:
            # Trigger background generation non-blockingly so the request doesn't hang
            try:
                import threading
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
            except Exception:
                pass

        raw_tokens = generator_bridge.read_tokens(region)
        valid_tokens = []
        for t in raw_tokens:
            token_str = get_token_str(t)
            if token_str and len(token_str) > 10:
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
        # All other regions (ME, BD, ID, VN, TH, PK, CIS, SG) use ppmainecoonghj
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
        response = requests.post(url, data=edata, headers=headers, verify=False, timeout=10)
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


# 🏠 Web UI Dashboard at /
@app.route('/')
def home_dashboard():
    tokens_info = generator_bridge.get_tokens_status()
    remaining = max(daily_limit - used_count, 0)
    html = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
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
            <h1>🔥 ARAFAT FLEX - FREE FIRE LIKE BOT</h1>
            <p>نظام زيادة لايكات فري فاير وإدارة التوكنات المتكامل (OB55)</p>
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

                <label>مفتاح API Key:</label>
                <input type="text" id="like_key" value="@ARAFAT_FLEX">

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
        async function loadStats() {
            try {
                const res = await fetch('/tokens/status?key=@ARAFAT_FLEX');
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
                const remainData = await remainRes.json();
                document.getElementById('remain_stat').innerText = `${remainData.remaining} / ${remainData.daily_limit} (مستخدم: ${remainData.used})`;
            } catch (e) {
                console.error(e);
            }
        }

        async function sendLikes() {
            const uid = document.getElementById('like_uid').value.trim();
            const region = document.getElementById('like_region').value;
            const key = document.getElementById('like_key').value.trim();
            const btn = document.getElementById('like_btn');
            const resBox = document.getElementById('like_result');

            if (!uid) { alert('يرجى إدخال UID اللاعب!'); return; }
            btn.disabled = true;
            btn.innerText = 'جاري إرسال الطلب... ⏳';
            resBox.style.display = 'block';
            resBox.innerText = 'جاري الاتصال بسيرفر فري فاير...';

            try {
                const response = await fetch(`/like?uid=${uid}&region=${region}&key=${encodeURIComponent(key)}`);
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
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({region: region, tokens: text, key: '@ARAFAT_FLEX'})
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
                const response = await fetch(`/generate?region=${region}&count=${count}&key=@ARAFAT_FLEX`);
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
    return render_template_string(html)


@app.route('/like', methods=['GET'])
def handle_requests():
    global used_count

    if not key_ok(request.args.get("key")):
        return {"error": "Invalid or missing API key"}, 401

    uid = request.args.get("uid")
    region = request.args.get("region", "").upper()
    if not uid or not region:
        return {"error": "UID and region are required"}, 400

    try:
        def process_request():
            global used_count

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
                    "error": "Failed to get initial info from Free Fire server. Check if token is valid or server is maintenance.",
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

            if status == 1:
                used_count += 1

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
        app.logger.error(f"Error: {e}")
        return {"error": str(e)}, 500


# 🆕 /tokens/add endpoint (Add raw tokens directly)
@app.route('/tokens/add', methods=['POST'])
def add_tokens_endpoint():
    data = request.get_json(silent=True) or {}
    key = data.get("key") or request.args.get("key")
    if not key_ok(key):
        return {"error": "Invalid or missing API key"}, 401

    region = (data.get("region") or request.args.get("region") or "BD").upper()
    raw_input = data.get("tokens") or ""

    entries_to_add = []
    if isinstance(raw_input, str):
        # Could be newline separated tokens or a JSON array string
        raw_input = raw_input.strip()
        if raw_input.startswith("[") and raw_input.endswith("]"):
            try:
                parsed = json.loads(raw_input)
                if isinstance(parsed, list):
                    for item in parsed:
                        tk = get_token_str(item)
                        if tk and len(tk) > 10:
                            entries_to_add.append({
                                "token": tk,
                                "jwt_token": tk,
                                "region": region
                            })
            except Exception:
                pass
        if not entries_to_add:
            # Parse line by line
            lines = raw_input.splitlines()
            for line in lines:
                tk = line.strip().strip('"').strip(',').strip()
                if tk and len(tk) > 10:
                    entries_to_add.append({
                        "token": tk,
                        "jwt_token": tk,
                        "region": region
                    })
    elif isinstance(raw_input, list):
        for item in raw_input:
            tk = get_token_str(item)
            if tk and len(tk) > 10:
                entries_to_add.append({
                    "token": tk,
                    "jwt_token": tk,
                    "region": region
                })

    if not entries_to_add:
        return {"error": "No valid tokens found in input."}, 400

    added = generator_bridge.append_tokens(region, entries_to_add)
    total = generator_bridge.count_valid_tokens(region)
    return jsonify({
        "status": "success",
        "region": region,
        "tokens_added": added,
        "total_available": total
    }), 200


# 🆕 /generate endpoint (On-demand token generation via TSun)
@app.route('/generate', methods=['GET', 'POST'])
def generate_endpoint():
    key = request.args.get("key") or (request.json.get("key") if request.is_json else None)
    if not key_ok(key):
        return {"error": "Invalid or missing API key"}, 401

    data = request.get_json(silent=True) or {}
    region = (request.args.get("region") or data.get("region") or "BD").upper()
    count = int(request.args.get("count") or data.get("count") or 10)
    count = max(1, min(count, 100))
    threads = int(request.args.get("threads") or data.get("threads") or 3)
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
            "check_status_url": f"/generate/status?job_id={job_id}&key={API_KEY}"
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
    if not key_ok(request.args.get("key")):
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
    if not key_ok(request.args.get("key")):
        return {"error": "Invalid or missing API key"}, 401

    return jsonify(generator_bridge.get_tokens_status())


# 🆕 /remain endpoint
@app.route('/remain', methods=['GET'])
def remain_info():
    global used_count

    remaining = max(daily_limit - used_count, 0)
    data = {
        "daily_limit": daily_limit,
        "remaining": remaining,
        "used": used_count,
        "reset_info": "4:00 AM IST"
    }
    return jsonify(data)


if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
    #join for more update :- @arafat_flex
    #Credit @arafat_flex , @arafat_source , @arafat_ahmed
