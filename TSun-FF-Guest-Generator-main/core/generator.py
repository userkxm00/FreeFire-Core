# Credits: TSun × Kittens
"""
core/generator.py
~~~~~~~~~~~~~~~~~
Account-generation orchestration: the single-account pipeline and the
multi-threaded worker loop.  All shared state is accessed through the
config.settings module to stay thread-safe.
"""

from __future__ import annotations

import time
import random

import config.settings as settings
from core.api import create_account
from features.rarity import check_account_rarity
from features.couples import check_account_couples
from storage.file_ops import (
    save_normal_account,
    save_jwt_token,
    save_rare_account,
    save_couples_account,
)
from ui.display import (
    get_random_color,
    Colors,
    print_success,
    print_warning,
    print_registration_status,
    print_rarity_found,
    print_couples_found,
)


def generate_single_account(
    region: str,
    account_name: str,
    password_prefix: str,
    total_accounts: int,
    thread_id: int,
    is_ghost: bool = False,
) -> dict | None:
    """
    Generate one account end-to-end, check rarity/couples, persist results.
    Returns the result dict or None on failure / quota reached.
    """
    if settings.EXIT_FLAG:
        return None

    with settings.LOCK:
        # Reserve one slot so total in-flight work never exceeds target.
        if settings.SUCCESS_COUNTER + settings.INFLIGHT_COUNTER >= total_accounts:
            return None
        settings.INFLIGHT_COUNTER += 1

    account = create_account(region, account_name, password_prefix, is_ghost)

    with settings.LOCK:
        if not account:
            settings.INFLIGHT_COUNTER = max(0, settings.INFLIGHT_COUNTER - 1)
            return None

        # Final guard: if quota is already filled, drop this completed account.
        if settings.SUCCESS_COUNTER >= total_accounts:
            settings.INFLIGHT_COUNTER = max(0, settings.INFLIGHT_COUNTER - 1)
            return None

        settings.SUCCESS_COUNTER += 1
        current_count = settings.SUCCESS_COUNTER
        settings.INFLIGHT_COUNTER = max(0, settings.INFLIGHT_COUNTER - 1)

    account_id = account.get("account_id", "N/A")
    jwt_token  = account.get("jwt_token", "")
    account["thread_id"] = thread_id

    print_registration_status(
        current_count, total_accounts,
        account["name"], account["uid"], account["password"],
        account_id, region, is_ghost,
    )

    # ── Rarity check ──────────────────────────────────────────────────────────
    is_rare, rarity_type, rarity_reason, rarity_score = check_account_rarity(account)
    if is_rare:
        rarity_type = rarity_type or "RARE_ACCOUNT"
        rarity_reason = rarity_reason or "Unknown rarity reason"
        with settings.LOCK:
            settings.RARE_COUNTER += 1
        print_rarity_found(account, rarity_type, rarity_reason, rarity_score)
        save_rare_account(account, rarity_type, rarity_reason, rarity_score, is_ghost)
        print_success(f"💎 Rare account saved! (Total rare: {settings.RARE_COUNTER})")

    # ── Couples check ─────────────────────────────────────────────────────────
    is_couple, couple_reason, partner = check_account_couples(account, thread_id)
    if is_couple and partner:
        couple_reason = couple_reason or "Unknown couples reason"
        with settings.LOCK:
            settings.COUPLES_COUNTER += 1
        print_couples_found(account, partner, couple_reason)
        save_couples_account(account, partner, couple_reason, is_ghost)
        print_success(f"💑 Couples saved! (Total couples: {settings.COUPLES_COUNTER})")

    # ── Persistence ───────────────────────────────────────────────────────────
    save_label = "GHOST" if is_ghost else region
    if save_normal_account(account, save_label, is_ghost=is_ghost):
        print_success(f"Account #{current_count} saved")
    else:
        print_warning(f"Account {account['uid']} already exists — skipped")

    if jwt_token:
        if save_jwt_token(account, jwt_token, save_label, is_ghost=is_ghost):
            print_success(f"JWT token saved for {account['uid']}")

    return {"account": account}


def worker(
    region: str,
    account_name: str,
    password_prefix: str,
    total_accounts: int,
    thread_id: int,
    is_ghost: bool = False,
) -> None:
    """Thread worker: keeps generating accounts until the quota is reached."""
    color = get_random_color()
    print(f"{color}{Colors.BRIGHT}🧵 Thread {thread_id} started{Colors.RESET}")

    generated = 0
    while not settings.EXIT_FLAG:
        with settings.LOCK:
            if settings.SUCCESS_COUNTER + settings.INFLIGHT_COUNTER >= total_accounts:
                break

        result = generate_single_account(
            region, account_name, password_prefix, total_accounts, thread_id, is_ghost
        )
        if result:
            generated += 1

        time.sleep(random.uniform(0.5, 1.5))

    print(f"{color}{Colors.BRIGHT}🧵 Thread {thread_id} done — {generated} accounts generated{Colors.RESET}")
