"""
fast_guest_generator.py
~~~~~~~~~~~~~~~~~~~~~~~
الجيل السريع لتوليد حسابات زائر (Guest Accounts) واستخراج التوكنات لسيرفر الشرق الأوسط (ME).
يعتمد على أتمتة المحاكي BlueStacks (FF LIKES) عبر ADB وتسجيل الحسابات على خوادم جارينا الرسمية.

السرعة: من 6 إلى 8 حسابات في الدقيقة (أو دورة سريعة من 10 إلى 15 ثانية لكل حساب).
"""

import argparse
import json
import logging
import os
import subprocess
import time
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("FastGuestGen")

ADB_PATH = r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe"
DEVICE_PORT = "127.0.0.1:5575"
PACKAGE_NAME = "com.dts.freefireth"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_ME_FILE = os.path.join(BASE_DIR, "token_me.json")

GARENA_TOKEN_URL = "https://ffmconnect.live.gop.garenanow.com/oauth/guest/token/grant"
GARENA_CLIENT_ID = "100067"
GARENA_CLIENT_SECRET = "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3"

def run_adb(cmd: str) -> str:
    full_cmd = f'"{ADB_PATH}" -s {DEVICE_PORT} {cmd}'
    res = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    return res.stdout.strip()

def connect_device() -> bool:
    logger.info(f"جاري الاتصال بالمحاكي {DEVICE_PORT}...")
    subprocess.run(f'"{ADB_PATH}" connect {DEVICE_PORT}', shell=True, capture_output=True)
    out = run_adb("get-state")
    if "device" in out:
        logger.info(f"تم الاتصال بنجاح بنسخة FF LIKES ({DEVICE_PORT})!")
        return True
    logger.error(f"تعذر الاتصال بالمحاكي. تأكد من تشغيل نسخة 'FF LIKES' في BlueStacks.")
    return False

def pull_guest_data() -> dict:
    raw = run_adb("shell cat /sdcard/com.garena.msdk/guest100067.dat")
    if not raw or "guest_account_info" not in raw:
        return {}
    try:
        data = json.loads(raw)
        info = data.get("guest_account_info", {})
        return {
            "uid": info.get("com.garena.msdk.guest_uid"),
            "password": info.get("com.garena.msdk.guest_password")
        }
    except Exception as e:
        logger.error(f"خطأ في قراءة ملف الضيف: {e}")
        return {}

def grant_garena_oauth(uid: str, password: str) -> dict:
    data = {
        "uid": uid,
        "password": password,
        "response_type": "token",
        "client_type": "2",
        "client_secret": GARENA_CLIENT_SECRET,
        "client_id": GARENA_CLIENT_ID,
    }
    headers = {
        "User-Agent": "GarenaMSDK/4.0.19P9(A063 ;Android 13;en;IN;)",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
    }
    try:
        resp = requests.post(GARENA_TOKEN_URL, data=data, headers=headers, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        logger.warning(f"خادم جارينا أعاد كود {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"خطأ في طلب التوكن: {e}")
    return {}

def clear_guest_file():
    run_adb("shell rm -f /sdcard/com.garena.msdk/guest100067.dat")

def restart_game_to_login():
    """إعادة تشغيل سريعة للعبة للعودة إلى شاشة تسجيل الدخول."""
    run_adb(f"shell am force-stop {PACKAGE_NAME}")
    time.sleep(1)
    run_adb(f"shell monkey -p {PACKAGE_NAME} -c android.intent.category.LAUNCHER 1")
    logger.info("جاري انتظار ظهور شاشة الدخول (حوالي 8-10 ثوانٍ)...")
    time.sleep(10)

def save_to_token_me(account_record: dict) -> int:
    tokens = []
    if os.path.exists(TOKEN_ME_FILE):
        try:
            with open(TOKEN_ME_FILE, "r", encoding="utf-8") as f:
                tokens = json.load(f)
        except Exception:
            tokens = []

    # تجنب تكرار التوكن أو UID
    existing_uids = {str(item.get("account_id") or item.get("uid") or "") for item in tokens}
    rec_uid = str(account_record.get("account_id") or account_record.get("uid") or "")
    if rec_uid and rec_uid in existing_uids:
        logger.info(f"الحساب {rec_uid} موجود مسبقاً في الملف.")
        return len(tokens)

    tokens.append(account_record)
    with open(TOKEN_ME_FILE, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2, ensure_ascii=False)
    return len(tokens)

def run_single_generation_cycle() -> bool:
    # التأكد من إزالة أي ملف ضيف سابق
    clear_guest_file()

    # 1. النقر على زر Guest (شاشة 1600x900)
    logger.info("1/4: الضغط على زر Guest...")
    run_adb("shell input tap 685 790")
    time.sleep(2.5)

    # 2. النقر على النرد لتوليد اسم عشوائي
    logger.info("2/4: الضغط على النرد لاختيار اسم فريد...")
    run_adb("shell input tap 1298 404")
    time.sleep(1.5)

    # 3. النقر على زر LET'S GO! لتسجيل الحساب رسمياً
    logger.info("3/4: الضغط على LET'S GO! وتأكيد التسجيل...")
    run_adb("shell input tap 1134 718")
    time.sleep(2.5)

    # 4. سحب بيانات الضيف المنشأة
    creds = pull_guest_data()
    if not creds.get("uid") or not creds.get("password"):
        logger.warning("لم يتم العثور على بيانات الحساب، جاري محاولة الضغط مجدداً...")
        run_adb("shell input tap 1134 718")
        time.sleep(2)
        creds = pull_guest_data()

    if not creds.get("uid") or not creds.get("password"):
        logger.error("تعذر قراءة بيانات الضيف.")
        return False

    logger.info(f"تم إنشاء الحساب بنجاح! UID: {creds['uid']}")

    # 5. استخراج التوكن عبر خادم Garena
    oauth = grant_garena_oauth(creds["uid"], creds["password"])
    if oauth.get("access_token"):
        record = {
            "token": oauth.get("access_token"),
            "open_id": oauth.get("open_id"),
            "account_id": creds["uid"],
            "password": creds["password"],
            "lock_region": "ME",
            "release_version": "OB55",
            "created_at": int(time.time())
        }
        total = save_to_token_me(record)
        logger.info(f"✓ تم استخراج التوكن وحفظ الحساب بنجاح! إجمالي الحسابات: {total}")
        return True
    else:
        logger.warning("فشل استخراج التوكن من جارينا.")
        return False

def generate_batch(count: int):
    logger.info(f"=== بدء توليد دفعة من {count} حساب لسيرفر الشرق الأوسط ME ===")
    if not connect_device():
        return

    success_count = 0
    for idx in range(1, count + 1):
        logger.info(f"--- [الحساب {idx}/{count}] ---")
        ok = run_single_generation_cycle()
        if ok:
            success_count += 1
        
        # إعادة التعيين لشاشة الدخول للحساب التالي
        if idx < count:
            logger.info("إعادة التعيين لشاشة الدخول للحساب القادم...")
            restart_game_to_login()

    logger.info(f"=== اكتملت العملية! تم توليد {success_count}/{count} حساب بنجاح ===")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="توليد حسابات Free Fire Guest تلقائياً عبر BlueStacks")
    parser.add_argument("--count", type=int, default=10, help="عدد الحسابات المراد توليدها (الافتراضي: 10)")
    args = parser.parse_args()

    generate_batch(args.count)
