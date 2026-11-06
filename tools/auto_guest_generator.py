"""
auto_guest_generator.py
~~~~~~~~~~~~~~~~~~~~~~~
Automated Free Fire Guest Account Generator via BlueStacks (ADB)
for region ME.

Workflow:
1. Connects to BlueStacks instance (FF LIKES) on 127.0.0.1:5575.
2. Automates UI clicks:
   - Clicks 'Guest' on login screen (X=685, Y=790)
   - Rolls random valid nickname via dice (X=1298, Y=404)
   - Confirms registration via 'LET'S GO!' (X=1134, Y=718)
3. Extracts guest credentials from /sdcard/com.garena.msdk/guest100067.dat
4. Exchanges credentials with Garena OAuth endpoint:
   https://ffmconnect.live.gop.garenanow.com/oauth/guest/token/grant
5. Saves accounts and tokens into token_me.json.
6. Cleans guest credential file on emulator for next run.
"""

import json
import logging
import os
import subprocess
import time
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("GuestGen")

ADB_PATH = r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe"
DEVICE_PORT = "127.0.0.1:5575"
TOKEN_ME_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "token_me.json")

GARENA_TOKEN_URL = "https://ffmconnect.live.gop.garenanow.com/oauth/guest/token/grant"
GARENA_CLIENT_ID = "100067"
GARENA_CLIENT_SECRET = "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3"

def run_adb(cmd: str) -> str:
    full_cmd = f'"{ADB_PATH}" -s {DEVICE_PORT} {cmd}'
    res = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    return res.stdout.strip()

def connect_device() -> bool:
    logger.info(f"Connecting to {DEVICE_PORT}...")
    subprocess.run(f'"{ADB_PATH}" connect {DEVICE_PORT}', shell=True, capture_output=True)
    out = run_adb("get-state")
    if "device" in out:
        logger.info(f"Connected successfully to {DEVICE_PORT}!")
        return True
    logger.error(f"Failed to connect to {DEVICE_PORT}. State: {out}")
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
        logger.error(f"Error parsing guest100067.dat: {e}")
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
        logger.warning(f"OAuth Grant returned {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"OAuth request error: {e}")
    return {}

def delete_emulator_guest_file():
    run_adb("shell rm -f /sdcard/com.garena.msdk/guest100067.dat")
    logger.info("Cleared guest100067.dat on emulator.")

def save_to_token_me(account_record: dict):
    tokens = []
    if os.path.exists(TOKEN_ME_FILE):
        try:
            with open(TOKEN_ME_FILE, "r", encoding="utf-8") as f:
                tokens = json.load(f)
        except Exception:
            tokens = []
            
    tokens.append(account_record)
    with open(TOKEN_ME_FILE, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)
    logger.info(f"Saved account to {TOKEN_ME_FILE}. Total accounts: {len(tokens)}")

def create_single_guest(target_nickname: str = None) -> bool:
    logger.info("Initiating Guest account creation...")
    
    # 1. Tap Guest
    logger.info("Tapping 'Guest' button...")
    run_adb("shell input tap 685 790")
    time.sleep(3)
    
    # 2. Tap Dice (random name)
    logger.info("Tapping Dice icon for nickname...")
    run_adb("shell input tap 1298 404")
    time.sleep(2)
    
    # 3. Tap LET'S GO!
    logger.info("Tapping 'LET'S GO!' button...")
    run_adb("shell input tap 1134 718")
    time.sleep(4)
    
    # 4. Pull credential file
    creds = pull_guest_data()
    if not creds.get("uid") or not creds.get("password"):
        logger.warning("Could not read credentials from guest100067.dat.")
        return False
        
    logger.info(f"Retrieved Guest UID: {creds['uid']}")
    
    # 5. Grant OAuth token
    oauth = grant_garena_oauth(creds["uid"], creds["password"])
    if oauth.get("access_token"):
        logger.info(f"OAuth Access Token granted! OpenID: {oauth.get('open_id')}")
        record = {
            "token": oauth.get("access_token"),
            "open_id": oauth.get("open_id"),
            "uid": creds["uid"],
            "password": creds["password"],
            "region": "ME",
            "created_at": int(time.time())
        }
        save_to_token_me(record)
        return True
        
    return False

if __name__ == "__main__":
    if connect_device():
        logger.info("Device ready for automated generation!")
    else:
        logger.error("Please ensure BlueStacks instance 'FF LIKES' is running.")
