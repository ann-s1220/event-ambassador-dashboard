"""CLI for managing the dashboard's authorized-user list.

Users are stored in config.yaml at the project root (gitignored -- never
commit it). Passwords are always hashed with bcrypt before they touch
disk; this script never writes plaintext.

Usage:
    python scripts/manage_users.py add-user
    python scripts/manage_users.py remove-user
    python scripts/manage_users.py list-users

Non-interactive form (password is still prompted, never taken as an
argument, so it never lands in shell history):
    python scripts/manage_users.py add-user --username jsmith --name "Jane Smith" --email jsmith@example.com
"""

import argparse
import getpass
import secrets
import sys
from pathlib import Path

import yaml
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            config = yaml.load(f, Loader=SafeLoader)
        config.setdefault("credentials", {}).setdefault("usernames", {})
        return config
    return {
        "cookie": {
            "name": "event_ambassador_auth",
            "key": secrets.token_hex(32),
            "expiry_days": 30,
        },
        "credentials": {"usernames": {}},
    }


def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


def add_user(args):
    config = load_config()
    usernames = config["credentials"]["usernames"]

    username = args.username or input("Username: ").strip()
    if not username:
        sys.exit("Username is required.")
    if username in usernames and not args.username:
        if input(f"'{username}' already exists -- overwrite? [y/N] ").strip().lower() != "y":
            sys.exit("Aborted.")

    name = args.name or input("Full name: ").strip()
    email = args.email or input("Email: ").strip()

    password = getpass.getpass("Password: ")
    if not password:
        sys.exit("Password is required.")
    if getpass.getpass("Confirm password: ") != password:
        sys.exit("Passwords did not match.")

    usernames[username] = {
        **{k: v for k, v in usernames.get(username, {}).items() if k not in (
            "name", "email", "password", "password_reset_requested", "password_reset_requested_at",
        )},
        "name": name,
        "email": email,
        "password": stauth.Hasher.hash(password),
    }
    save_config(config)
    print(f"Added/updated '{username}' in {CONFIG_PATH}.")


def remove_user(args):
    config = load_config()
    usernames = config["credentials"]["usernames"]

    username = args.username or input("Username to remove: ").strip()
    if username not in usernames:
        sys.exit(f"'{username}' not found.")

    del usernames[username]
    save_config(config)
    print(f"Removed '{username}' from {CONFIG_PATH}.")


def list_users(args):
    config = load_config()
    usernames = config["credentials"]["usernames"]

    if not usernames:
        print("No users configured yet.")
        return
    for username, info in usernames.items():
        flag = " [password reset requested]" if info.get("password_reset_requested") else ""
        print(f"{username}\t{info.get('name', '')}\t{info.get('email', '')}{flag}")


def main():
    parser = argparse.ArgumentParser(description="Manage authorized dashboard users.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add-user", help="Add a new user or reset an existing one's password")
    p_add.add_argument("--username")
    p_add.add_argument("--name")
    p_add.add_argument("--email")
    p_add.set_defaults(func=add_user)

    p_remove = sub.add_parser("remove-user", help="Revoke a user's access")
    p_remove.add_argument("--username")
    p_remove.set_defaults(func=remove_user)

    p_list = sub.add_parser("list-users", help="List authorized usernames")
    p_list.set_defaults(func=list_users)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
