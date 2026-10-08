#!/usr/bin/env python3
"""
One-time setup helper. Double-click setup.bat (Windows) or run: python setup.py

It will:
  1. Ask for your keys and save them in a private .env file in this folder
  2. Check your eBay keys work
  3. Connect your Pinterest account
  4. Create your Pinterest boards and save their IDs into config.yaml
  5. Do a test run that finds deals without posting anything
  6. Show you exactly what to paste into GitHub

You can run it again at any time. It skips anything already done.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent
ENV_FILE = ROOT / ".env"

KEYS = [
    ("EBAY_CLIENT_ID", "eBay App ID (Client ID)", True),
    ("EBAY_CLIENT_SECRET", "eBay Cert ID (Client Secret)", True),
    ("EPN_CAMPAIGN_ID", "eBay Partner Network Campaign ID (10 digits)", True),
    ("PINTEREST_APP_ID", "Pinterest App ID", True),
    ("PINTEREST_APP_SECRET", "Pinterest App secret key", True),
    ("AWIN_FEED_BEAUTY", "Awin beauty/fragrance feed link (press Enter to skip for now)", False),
    ("AWIN_FEED_KIDS", "Awin baby/kids feed link (press Enter to skip for now)", False),
]


def read_env():
    vals = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip()
    return vals


def write_env(vals):
    lines = ["# Private keys for the deal bot. Never upload this file anywhere."]
    lines += [f"{k}={v}" for k, v in vals.items() if v]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for k, v in vals.items():
        if v:
            os.environ[k] = v


def step(n, title):
    print(f"\n{'=' * 60}\nStep {n}: {title}\n{'=' * 60}")


def main():
    try:
        import requests  # noqa: F401
        import yaml  # noqa: F401
    except ImportError:
        sys.exit("Missing libraries. Run: pip install -r requirements.txt")

    vals = read_env()

    step(1, "Your keys")
    print("Paste each key and press Enter. Keys already saved are skipped.")
    for key, label, required in KEYS:
        if vals.get(key):
            print(f"  {label}: already saved")
            continue
        while True:
            v = input(f"  {label}: ").strip()
            if v or not required:
                break
            print("    This one is needed. Find it using the setup checklist.")
        vals[key] = v
        write_env(vals)
    write_env(vals)

    import dealbot  # imported after .env exists so it picks the keys up

    step(2, "Checking eBay")
    try:
        dealbot.ebay_token()
        print("  eBay keys work.")
    except Exception as e:
        print(f"  eBay rejected the keys: {e}")
        print("  Check you copied the PRODUCTION keyset (not Sandbox), then run setup again.")
        vals.pop("EBAY_CLIENT_ID", None)
        vals.pop("EBAY_CLIENT_SECRET", None)
        write_env(vals)
        sys.exit(1)

    if vals.get("PINTEREST_STANDARD") != "yes":
        print("\nHas Pinterest approved your app for STANDARD access yet?")
        print("(Until then, anything the bot creates on Pinterest stays private.)")
        if input("Type yes or no: ").strip().lower().startswith("y"):
            vals["PINTEREST_STANDARD"] = "yes"
            write_env(vals)
        else:
            print("\nNo problem. Next:")
            print("  1. Double-click demo.bat and record your screen while it runs.")
            print("  2. On developers.pinterest.com, request Standard access and upload the video.")
            print("  3. Once approved, run setup.bat again to finish.")
            return

    step(3, "Connecting Pinterest")
    if vals.get("PINTEREST_REFRESH_TOKEN"):
        print("  Already connected.")
    else:
        vals["PINTEREST_REFRESH_TOKEN"] = dealbot.cmd_auth()
        write_env(vals)

    step(4, "Creating your Pinterest boards")
    dealbot.cmd_create_boards(dealbot.load_config())

    step(5, "Test run (finds deals, posts nothing)")
    dealbot.cmd_run(dealbot.load_config(), dry_run=True)

    step(6, "Copy these into GitHub")
    print("In your GitHub repo: Settings > Secrets and variables > Actions >")
    print("New repository secret. Add each one below (name, then value):\n")
    names = [k for k, _, _ in KEYS] + ["PINTEREST_REFRESH_TOKEN"]
    for k in names:
        if vals.get(k):
            print(f"  {k}\n    {vals[k]}\n")
    print("Then upload the updated config.yaml to GitHub (it now has your board IDs).")
    print("Do NOT upload the .env file. It holds your private keys.")
    print("\nAll done.")


if __name__ == "__main__":
    main()
