# Credits: TSun × Kittens
"""
ui/display.py
~~~~~~~~~~~~~
Console output utilities: coloured print helpers, the ASCII-art banner,
registration status display, and terminal control (clear, safe exit).
"""

from __future__ import annotations

import os
import sys
import random

from colorama import Fore, Style, init

import config.settings as settings

# Initialise colorama once at import time
init(autoreset=True)


# ── Colour helpers ────────────────────────────────────────────────────────────

class Colors:
    BRIGHT = Style.BRIGHT
    RESET  = Style.RESET_ALL


def get_random_color() -> str:
    """Return a random bright terminal colour."""
    return random.choice([
        Fore.LIGHTGREEN_EX,
        Fore.LIGHTYELLOW_EX,
        Fore.LIGHTWHITE_EX,
        Fore.LIGHTBLUE_EX,
    ])


# ── Terminal control ──────────────────────────────────────────────────────────

def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def safe_exit(signum=None, frame=None) -> None:
    """Signal-safe shutdown handler."""
    settings.EXIT_FLAG = True
    color = get_random_color()
    print(f"\n{color}{Colors.BRIGHT}🚨 Safe exit triggered. Closing script...{Colors.RESET}")
    sys.exit(0)


# ── Banner ────────────────────────────────────────────────────────────────────

def display_banner() -> None:
    color = get_random_color()
    banner = f"""
{color}{Colors.BRIGHT}
 ████████╗███████╗██╗   ██╗███╗   ██╗
 ╚══██╔══╝██╔════╝██║   ██║████╗  ██║
    ██║   ███████╗██║   ██║██╔██╗ ██║
    ██║   ╚════██║██║   ██║██║╚██╗██║
    ██║   ███████║╚██████╔╝██║ ╚████║
    ╚═╝   ╚══════╝ ╚═════╝ ╚═╝  ╚═══╝

 ██╗  ██╗██╗████████╗████████╗███████╗███╗   ██╗███████╗
 ██║ ██╔╝██║╚══██╔══╝╚══██╔══╝██╔════╝████╗  ██║██╔════╝
 █████╔╝ ██║   ██║      ██║   █████╗  ██╔██╗ ██║███████╗
 ██╔═██╗ ██║   ██║      ██║   ██╔══╝  ██║╚██╗██║╚════██║
 ██║  ██╗██║   ██║      ██║   ███████╗██║ ╚████║███████║
 ╚═╝  ╚═╝╚═╝   ╚═╝      ╚═╝   ╚══════╝╚═╝  ╚═══╝╚══════╝

{settings.CLIENT_DATA}

{Colors.RESET}
"""
    print(banner)


# ── Generic print helpers ─────────────────────────────────────────────────────

def print_success(message: str) -> None:
    print(f"{get_random_color()}{Colors.BRIGHT}✅ {message}{Colors.RESET}")


def print_error(message: str) -> None:
    print(f"{Fore.RED}{Colors.BRIGHT}❌ {message}{Colors.RESET}")


def print_warning(message: str) -> None:
    print(f"{Fore.YELLOW}{Colors.BRIGHT}⚠️  {message}{Colors.RESET}")


def print_rare(message: str) -> None:
    print(f"{Fore.LIGHTMAGENTA_EX}{Colors.BRIGHT}💎 {message}{Colors.RESET}")


# ── Specialised status printers ───────────────────────────────────────────────

def print_registration_status(
    count: int,
    total: int,
    name: str,
    uid: str,
    password: str,
    account_id: str,
    region: str,
    is_ghost: bool = False,
) -> None:
    c = get_random_color
    print(f"{c()}{Colors.BRIGHT}📋 Registration {count}/{total}{Colors.RESET}")
    print(f"{c()}👤 Name:       {c()}{name}{Colors.RESET}")
    print(f"{c()}🆔 UID:        {c()}{uid}{Colors.RESET}")
    print(f"{c()}🔢 Account ID: {c()}{account_id}{Colors.RESET}")
    print(f"{c()}🔑 Password:   {c()}{password}{Colors.RESET}")
    if is_ghost:
        print(f"{c()}🌍 Mode: {Fore.LIGHTMAGENTA_EX}GHOST Mode{Colors.RESET}")
    else:
        print(f"{c()}🌍 Region:     {c()}{region}{Colors.RESET}")
    print()


def print_rarity_found(
    account_data: dict,
    rarity_type: str,
    reason: str,
    rarity_score: int,
) -> None:
    color = Fore.LIGHTMAGENTA_EX
    print(f"\n{color}{Colors.BRIGHT}💎 RARE ACCOUNT FOUND!{Colors.RESET}")
    print(f"{color}🎯 Type:        {rarity_type}{Colors.RESET}")
    print(f"{color}⭐ Score:       {rarity_score}{Colors.RESET}")
    print(f"{color}👤 Name:        {account_data['name']}{Colors.RESET}")
    print(f"{color}🆔 UID:         {account_data['uid']}{Colors.RESET}")
    print(f"{color}🔢 Account ID:  {account_data.get('account_id', 'N/A')}{Colors.RESET}")
    print(f"{color}📝 Reason:      {reason}{Colors.RESET}")
    print(f"{color}🧵 Thread:      {account_data.get('thread_id', 'N/A')}{Colors.RESET}")
    print(f"{color}🌍 Region:      {account_data.get('region', 'N/A')}{Colors.RESET}\n")


def print_couples_found(account1: dict, account2: dict, reason: str) -> None:
    color = Fore.LIGHTCYAN_EX
    print(f"\n{color}{Colors.BRIGHT}💑 COUPLES ACCOUNT FOUND!{Colors.RESET}")
    print(f"{color}📝 Reason:    {reason}{Colors.RESET}")
    print(
        f"{color}👤 Account 1: {account1['name']} "
        f"(ID: {account1.get('account_id', 'N/A')}) "
        f"- Thread {account1.get('thread_id', 'N/A')}{Colors.RESET}"
    )
    print(
        f"{color}👤 Account 2: {account2['name']} "
        f"(ID: {account2.get('account_id', 'N/A')}) "
        f"- Thread {account2.get('thread_id', 'N/A')}{Colors.RESET}"
    )
    print(f"{color}🆔 UIDs:      {account1['uid']} & {account2['uid']}{Colors.RESET}")
    print(f"{color}🌍 Region:    {account1.get('region', 'N/A')}{Colors.RESET}\n")
