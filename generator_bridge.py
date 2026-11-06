"""
generator_bridge.py
~~~~~~~~~~~~~~~~~~~
Bridge module connecting TSun FF Guest Generator with the Like API.
Provides:
  - Unified token loading and saving (supporting both 'token' and 'jwt_token')
  - Automatic token refill when tokens run low (Auto-Refill)
  - Synchronous and asynchronous on-demand token generation
  - Multi-region token status tracking
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("generator_bridge")

# Add TSun generator directory to sys.path
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_TSUN_DIR = os.path.join(_CURRENT_DIR, "TSun-FF-Guest-Generator-main")
if _TSUN_DIR not in sys.path:
    sys.path.insert(0, _TSUN_DIR)



# Import TSun core components
try:
    import config.settings as tsun_settings
    from core.api import create_account
    from features.couples import check_account_couples
    from features.rarity import check_account_rarity
    from storage.file_ops import (
        save_couples_account,
        save_jwt_token,
        save_normal_account,
        save_rare_account,
    )
except ImportError as e:
    raise ImportError(f"Failed to import TSun generator modules from {_TSUN_DIR}: {e}")

# Global lock for file operations and token generation
_BRIDGE_LOCK = threading.Lock()
_REGION_GENERATING_LOCKS: Dict[str, threading.Lock] = {}
_ACTIVE_JOBS: Dict[str, Dict[str, Any]] = {}

# Set of all valid regions supported across Garena / Free Fire
SUPPORTED_REGIONS = {
    "BD", "IND", "BR", "US", "SAC", "NA", "ME", "ID", "VN", "TH", "PK", "CIS", "SG", "TW"
}


def _get_region_lock(region: str) -> threading.Lock:
    with _BRIDGE_LOCK:
        reg = region.upper()
        if reg not in _REGION_GENERATING_LOCKS:
            _REGION_GENERATING_LOCKS[reg] = threading.Lock()
        return _REGION_GENERATING_LOCKS[reg]


def _cleanup_old_jobs(max_age_seconds: int = 3600) -> None:
    """Remove completed or errored jobs older than max_age_seconds to prevent memory leaks."""
    now = time.time()
    with _BRIDGE_LOCK:
        to_delete = []
        for j_id, j_data in _ACTIVE_JOBS.items():
            if j_data.get("status") in {"finished", "error"}:
                created_ts = j_data.get("created_ts", now)
                if now - created_ts > max_age_seconds:
                    to_delete.append(j_id)
        for j_id in to_delete:
            _ACTIVE_JOBS.pop(j_id, None)


# ── File and Region Mapping Helpers ───────────────────────────────────────────

def get_token_filepath(region: str) -> str:
    """Return the absolute path of the root token file for the given region."""
    reg = (region or "BD").upper()
    if reg == "IND":
        filename = "token_ind.json"
    elif reg in {"BR", "US", "SAC", "NA"}:
        filename = "token_br.json"
    elif reg == "BD":
        filename = "token_bd.json"
    else:
        filename = f"token_{reg.lower()}.json"
    return os.path.join(_CURRENT_DIR, filename)


def map_to_tsun_region(region: str) -> str:
    """
    Map API region code to TSun supported region code.
    Raises ValueError if region is completely unknown/unsupported.
    """
    if not region:
        raise ValueError("Region parameter cannot be empty.")
    reg = region.upper().strip()
    if reg in {"US", "NA"}:
        return "SAC"
    if reg == "BR":
        return "BR"
    if reg in tsun_settings.REGION_LANG:
        return reg

    raise ValueError(
        f"Region '{region}' is not supported. Supported regions: {sorted(list(SUPPORTED_REGIONS))}"
    )


# ── Token I/O Helpers ─────────────────────────────────────────────────────────

def read_tokens(region: str) -> List[Dict[str, Any]]:
    """
    Read tokens from the region's JSON file.
    Always returns a list of dictionaries. Creates file if missing.
    Backs up corrupted file if invalid JSON is detected.
    """
    filepath = get_token_filepath(region)
    if not os.path.exists(filepath):
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump([], f)
        return []

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            logger.warning(f"Token file {filepath} was not a list, resetting.")
            return []
    except (json.JSONDecodeError, IOError) as exc:
        logger.error(f"Error reading JSON from {filepath}: {exc}")
        # Back up corrupted file
        try:
            corrupt_backup = filepath + f".corrupt_{int(time.time())}"
            os.replace(filepath, corrupt_backup)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump([], f)
        except Exception:
            pass
        return []


def count_valid_tokens(region: str) -> int:
    """Count tokens that have a valid non-empty JWT string."""
    tokens = read_tokens(region)
    count = 0
    for t in tokens:
        if isinstance(t, dict):
            jwt = t.get("token") or t.get("jwt_token")
            if jwt and isinstance(jwt, str) and len(jwt.strip()) > 10:
                count += 1
        elif isinstance(t, str) and len(t.strip()) > 10:
            count += 1
    return count


def append_tokens(region: str, new_entries: List[Dict[str, Any]]) -> int:
    """
    Append new token entries to the region's file atomically.
    Deduplicates by account_id and token string.
    """
    if not new_entries:
        return 0

    filepath = get_token_filepath(region)
    lock = _get_region_lock(region)

    with lock:
        existing = read_tokens(region)
        existing_tokens = set()
        for e in existing:
            if isinstance(e, dict):
                tk = e.get("token") or e.get("jwt_token") or ""
                aid = e.get("account_id") or ""
                if tk:
                    existing_tokens.add(tk.strip())
                if aid:
                    existing_tokens.add(str(aid).strip())

        added = 0
        for item in new_entries:
            tk = (item.get("token") or item.get("jwt_token") or "").strip()
            aid = str(item.get("account_id") or "").strip()
            if tk and tk not in existing_tokens and (not aid or aid not in existing_tokens):
                existing.append(item)
                existing_tokens.add(tk)
                if aid:
                    existing_tokens.add(aid)
                added += 1

        tmp_file = filepath + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
        os.replace(tmp_file, filepath)
        return added


# ── Account / Token Generation Engine ─────────────────────────────────────────

def generate_tokens(
    region: str = "BD",
    count: int = 10,
    threads: int = 3,
    name_prefix: str = "ARAFAT",
    pass_prefix: str = "Flex",
    is_ghost: bool = False,
    progress_callback: Optional[Callable[[int, int, Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """
    Generate accounts and extract JWT tokens using TSun engine.
    Saves results to BOTH TSun-Studio and root token files.
    """
    reg_upper = region.upper()
    tsun_reg = map_to_tsun_region(reg_upper)
    lock = _get_region_lock(reg_upper)

    with lock:
        total_target = max(1, count)
        collected_tokens: List[Dict[str, Any]] = []
        success_count = 0
        counter_lock = threading.Lock()

        def _worker(thread_idx: int):
            nonlocal success_count
            attempts = 0
            max_thread_attempts = max(3, total_target * 2)
            while attempts < max_thread_attempts and not tsun_settings.EXIT_FLAG:
                attempts += 1
                with counter_lock:
                    if success_count >= total_target:
                        break

                acc = create_account(
                    region=tsun_reg,
                    account_name=name_prefix,
                    password_prefix=pass_prefix,
                    is_ghost=is_ghost,
                )

                if not acc or not acc.get("jwt_token"):
                    time.sleep(0.5)
                    continue

                jwt_token = acc["jwt_token"]
                account_id = acc.get("account_id", "N/A")
                uid = acc.get("uid", "")
                name = acc.get("name", "")
                pwd = acc.get("password", "")

                with counter_lock:
                    if success_count >= total_target:
                        break
                    success_count += 1
                    current = success_count

                # Format token entry (contains both 'token' and 'jwt_token')
                token_entry = {
                    "token": jwt_token,
                    "jwt_token": jwt_token,
                    "uid": uid,
                    "account_id": account_id,
                    "name": name,
                    "password": pwd,
                    "region": reg_upper,
                    "date_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "thread_id": thread_idx,
                }

                with counter_lock:
                    collected_tokens.append(token_entry)

                # Also save to TSun Studio folders so rare & normal accounts are preserved
                save_label = "GHOST" if is_ghost else tsun_reg
                save_normal_account(acc, save_label, is_ghost=is_ghost)
                save_jwt_token(acc, jwt_token, save_label, is_ghost=is_ghost)

                # Rarity check
                is_rare, rarity_type, rarity_reason, rarity_score = check_account_rarity(acc)
                if is_rare:
                    save_rare_account(
                        acc,
                        rarity_type or "RARE",
                        rarity_reason or "Unknown",
                        rarity_score,
                        is_ghost=is_ghost,
                    )

                # Couples check
                is_cpl, cpl_reason, partner = check_account_couples(acc, thread_idx)
                if is_cpl and partner:
                    save_couples_account(acc, partner, cpl_reason or "Couple", is_ghost=is_ghost)

                if progress_callback:
                    try:
                        progress_callback(current, total_target, token_entry)
                    except Exception:
                        pass

                time.sleep(0.2)

        # Launch worker threads
        actual_threads = min(threads, total_target, 8)
        workers = []
        for i in range(actual_threads):
            t = threading.Thread(target=_worker, args=(i + 1,), daemon=True)
            t.start()
            workers.append(t)

        for t in workers:
            t.join(timeout=60)

        # Append collected tokens to root token file
        saved_count = append_tokens(reg_upper, collected_tokens)

        return {
            "region": reg_upper,
            "target": total_target,
            "generated": len(collected_tokens),
            "tokens_saved": saved_count,
            "total_available": count_valid_tokens(reg_upper),
            "status": "success" if collected_tokens else "failed",
        }


# ── Auto-Refill Logic ─────────────────────────────────────────────────────────

def ensure_tokens_available(
    region: str,
    min_tokens: int = 5,
    refill_amount: int = 15,
    threads: int = 3,
) -> Tuple[int, bool]:
    """
    Ensure the region has at least `min_tokens`.
    If count < min_tokens, automatically generate `refill_amount` tokens.
    Returns (current_token_count, did_refill).
    """
    current_count = count_valid_tokens(region)
    if current_count >= min_tokens:
        return current_count, False

    try:
        generate_tokens(
            region=region,
            count=refill_amount,
            threads=threads,
            name_prefix="Arafat",
            pass_prefix="Flex",
        )
    except Exception as e:
        logger.warning(f"ensure_tokens_available failed for {region}: {e}")

    new_count = count_valid_tokens(region)
    return new_count, True


# ── Multi-Region Status ───────────────────────────────────────────────────────

def get_tokens_status() -> Dict[str, Any]:
    """Return token count and files overview for all known regions."""
    regions = sorted(list(SUPPORTED_REGIONS))
    summary: Dict[str, Any] = {}
    total_all = 0

    for reg in regions:
        c = count_valid_tokens(reg)
        summary[reg] = {
            "valid_tokens": c,
            "file": os.path.basename(get_token_filepath(reg)),
        }
        total_all += c

    return {
        "regions": summary,
        "total_tokens_across_all": total_all,
    }


# ── Asynchronous Background Generation Job Manager ────────────────────────────

def start_background_generation(
    region: str,
    count: int = 15,
    threads: int = 3,
    name_prefix: str = "Arafat",
    pass_prefix: str = "Flex",
) -> str:
    """Start token generation in a background thread and return job ID."""
    _cleanup_old_jobs()
    job_id = f"job_{region.upper()}_{int(time.time())}"
    with _BRIDGE_LOCK:
        _ACTIVE_JOBS[job_id] = {
            "job_id": job_id,
            "region": region.upper(),
            "target": count,
            "completed": 0,
            "status": "running",
            "created_ts": time.time(),
            "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _progress(current: int, total: int, _entry: dict):
        with _BRIDGE_LOCK:
            if job_id in _ACTIVE_JOBS:
                _ACTIVE_JOBS[job_id]["completed"] = current

    def _run():
        try:
            result = generate_tokens(
                region=region,
                count=count,
                threads=threads,
                name_prefix=name_prefix,
                pass_prefix=pass_prefix,
                progress_callback=_progress,
            )
            with _BRIDGE_LOCK:
                if job_id in _ACTIVE_JOBS:
                    _ACTIVE_JOBS[job_id]["status"] = "finished"
                    _ACTIVE_JOBS[job_id]["result"] = result
        except Exception as exc:
            with _BRIDGE_LOCK:
                if job_id in _ACTIVE_JOBS:
                    _ACTIVE_JOBS[job_id]["status"] = "error"
                    _ACTIVE_JOBS[job_id]["error"] = str(exc)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return job_id


def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    with _BRIDGE_LOCK:
        job = _ACTIVE_JOBS.get(job_id)
        if job:
            return dict(job)
        return None
