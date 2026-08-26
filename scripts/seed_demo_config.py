"""Creates config.demo.yaml with the single 'demo' account used on this
branch (see the README's "You're on the demo branch" note). Safe to
re-run any time -- it overwrites the file with a fresh cookie signing
key and a freshly-hashed password, so this is also how you'd rotate the
demo password if it ever needed to change.

Usage:
    python scripts/seed_demo_config.py
"""
import secrets
from pathlib import Path

import yaml
import streamlit_authenticator as stauth

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.demo.yaml"

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo123"


def main():
    config = {
        "cookie": {
            "name": "event_ambassador_demo_auth",
            "key": secrets.token_hex(32),
            "expiry_days": 30,
        },
        "credentials": {
            "usernames": {
                DEMO_USERNAME: {
                    "name": "Demo User",
                    "email": "demo@example.com",
                    "password": stauth.Hasher.hash(DEMO_PASSWORD),
                    "roles": ["admin"],
                }
            }
        },
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    print(f"Wrote {CONFIG_PATH} -- login with '{DEMO_USERNAME}' / '{DEMO_PASSWORD}'.")


if __name__ == "__main__":
    main()
