import json
import os
import secrets

import streamlit as st
import streamlit.components.v1 as components
import yaml
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth
from streamlit_authenticator.utilities import CredentialsError, LoginError, ResetError

import db
from auth_helpers import (
    clear_pending_reset_notice_on_logout, render_forgot_password_section,
    render_login_form, render_pending_reset_notice,
)
from style import get_css
from tabs import ambassadors, attendance, data_management, feedback

st.set_page_config(page_title="Event & Ambassador Dashboard", layout="wide")

# demo branch only: a distinct filename from main's config.yaml, so this
# branch's demo account (see the login-screen note below) can never be
# used to authenticate against whatever real config main is using in the
# same working copy, and vice versa.
CONFIG_PATH = "config.demo.yaml"

# Native st.tabs() is the single source of truth for which section is
# showing -- all four are rendered every run (exactly as before the
# sidebar existed), and clicking one works natively, client-side, with no
# Python round-trip. The sidebar buttons don't render their own content;
# a sidebar click instead asks a tiny injected script to click the
# matching native tab on Streamlit's behalf (see the components.html call
# below), and that same script keeps the sidebar's highlight in sync with
# whichever tab is actually selected, via a MutationObserver watching
# aria-selected -- so a direct tab click updates the sidebar too, with no
# Python state involved on that side at all.
SECTION_NAMES = [
    "Member attendance", "Ambassador performance", "Member feedback", "Data management (GDPR)",
]
SECTION_MODULES = [attendance, ambassadors, feedback, data_management]

if "_dark_mode_pref" not in st.session_state:
    st.session_state["_dark_mode_pref"] = True

# Login form and any not-yet-authenticated messaging need the theme too,
# so this first injection uses whatever the preference currently holds
# (the default, since the toggle itself only exists in the sidebar below,
# which is gated behind a successful login).
st.markdown(get_css(st.session_state["_dark_mode_pref"]), unsafe_allow_html=True)

st.title("Event & Ambassador Dashboard")

# demo branch only. config.demo.yaml is gitignored, same as main's real
# config.yaml -- but unlike main, there's no real credential to protect
# here (demo/demo123 is printed on the login screen below, publicly, on
# purpose), so a fresh checkout or deploy just gets it auto-created
# instead of erroring out asking for a manual setup step. main's app.py
# has no equivalent of this block; it still requires config.yaml to
# already exist, with no auto-creation fallback.
if not os.path.exists(CONFIG_PATH):
    demo_config = {
        "cookie": {
            "name": "event_ambassador_demo_auth",
            "key": secrets.token_hex(32),
            "expiry_days": 30,
        },
        "credentials": {
            "usernames": {
                "demo": {
                    "name": "Demo User",
                    "email": "demo@example.com",
                    "password": stauth.Hasher.hash("demo123"),
                    "roles": ["admin"],
                }
            }
        },
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(demo_config, f, default_flow_style=False, allow_unicode=True)

def save_auth_config() -> None:
    """Persist auth_config back to CONFIG_PATH. Needed because we hand
    Authenticate a dict (not a file path) -- the library only auto-persists
    its own changes when constructed from a path, so anything that mutates
    auth_config in-session (a password reset, a new teammate) has to write
    it back out manually."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(auth_config, f, default_flow_style=False, allow_unicode=True)


with open(CONFIG_PATH, encoding="utf-8") as f:
    auth_config = yaml.load(f, Loader=SafeLoader)

st.session_state["_auth_config"] = auth_config
st.session_state["_config_path"] = CONFIG_PATH
st.session_state["_save_auth_config"] = save_auth_config

authenticator = stauth.Authenticate(
    auth_config["credentials"],
    auth_config["cookie"]["name"],
    auth_config["cookie"]["key"],
    auth_config["cookie"]["expiry_days"],
)

# demo branch only -- shown on the login screen (hidden again once
# actually logged in, so it doesn't linger in the way once past it).
if not st.session_state.get("authentication_status"):
    st.info("**Demo login** — Username: `demo`  |  Password: `demo123`")

try:
    render_login_form(authenticator, auth_config)
except LoginError as e:
    st.error(str(e))
    st.stop()

render_forgot_password_section(auth_config, save_auth_config)

auth_status = st.session_state.get("authentication_status")
if auth_status is False:
    st.error("Username or password is incorrect.")
    st.stop()
elif auth_status is None:
    st.warning("Please enter your username and password.")
    st.stop()

current_username = st.session_state.get("username")
current_user_entry = auth_config["credentials"]["usernames"].get(current_username, {})

# Teammates added via the admin "Add teammate" form (Data management tab)
# start with a temporary password and this flag set -- they're shown
# nothing else until they set their own password. reset_password() also
# requires re-entering the temporary password, which doubles as proof
# they were actually given it.
if current_user_entry.get("must_change_password"):
    st.info("Your account was created with a temporary password. Set your own password to continue.")
    try:
        if authenticator.reset_password(
            current_username, fields={"Form name": "Set your new password"}
        ):
            auth_config["credentials"]["usernames"][current_username]["must_change_password"] = False
            save_auth_config()
            st.success("Password updated.")
            st.rerun()
    except (CredentialsError, ResetError) as e:
        st.error(str(e))
    st.stop()

# --- Everything below only runs for a signed-in, authorized user. ---

is_admin = "admin" in (current_user_entry.get("roles") or [])
render_pending_reset_notice(auth_config, is_admin, SECTION_NAMES)

with st.sidebar:
    st.markdown(f"Signed in as **{st.session_state.get('name')}**")
    authenticator.logout("Logout", "sidebar", callback=clear_pending_reset_notice_on_logout)
    st.divider()
    st.markdown("**Navigate**")
    for i, name in enumerate(SECTION_NAMES):
        if st.button(name, key=f"nav_{name}", width="stretch"):
            st.session_state["_pending_tab_click"] = i
            st.rerun()
    st.divider()
    # A plain `st.toggle(..., key="dark_mode")` intermittently reverted to
    # its unset default (False) on reruns triggered by a widget inside one
    # of the st.tabs() bodies (confirmed via logging -- reproduces even on
    # pre-existing buttons unrelated to any single feature, so it's a
    # platform-level widget-state quirk, not application logic). Tracking
    # the preference in our own `_dark_mode_pref` key and feeding it back
    # in as the toggle's `value=` every run sidesteps it: `value=` wins
    # over whatever the widget's own persisted state would otherwise be,
    # so a corrupted "dark_mode" key can't silently flip the theme.
    def _sync_dark_mode_pref():
        st.session_state["_dark_mode_pref"] = st.session_state["dark_mode"]

    st.toggle(
        "Dark mode", value=st.session_state["_dark_mode_pref"], key="dark_mode",
        on_change=_sync_dark_mode_pref,
    )

dark_mode = st.session_state["_dark_mode_pref"]
st.markdown(get_css(dark_mode), unsafe_allow_html=True)

db.init_db()
conn = db.get_connection()

# demo branch only. A fixed, frozen dataset (scripts/demo_seed_data.py,
# a snapshot committed to this branch) rather than regenerating random
# data on every startup -- so anyone opening the demo link sees the same
# events, members, ambassador rankings, and feedback every time, which
# is the point for referencing specific examples (e.g. in an interview).
# Checked on every run, not just once, since Streamlit Cloud's
# filesystem is ephemeral -- a fresh container restart means a fresh,
# empty database again, same as a first-ever run.
if conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0:
    from scripts.demo_seed_data import load_into
    load_into(conn)

tabs = st.tabs(SECTION_NAMES)
for tab, module in zip(tabs, SECTION_MODULES):
    with tab:
        module.render(conn)

pending_click = st.session_state.pop("_pending_tab_click", None)
components.html(
    f"""
    <script>
    (function() {{
        const doc = window.parent.document;
        const names = {json.dumps(SECTION_NAMES)};
        const pending = {json.dumps(pending_click)};

        function getTabs() {{
            return [...doc.querySelectorAll('[role="tablist"] [data-testid="stTab"]')];
        }}
        function getNavButtons() {{
            const sidebar = doc.querySelector('[data-testid="stSidebar"]');
            if (!sidebar) return [];
            const buttons = [...sidebar.querySelectorAll('button')];
            return names.map(n => buttons.find(b => b.textContent.trim() === n));
        }}
        function highlightActive() {{
            const tabEls = getTabs();
            const navButtons = getNavButtons();
            let activeIdx = -1;
            tabEls.forEach((t, i) => {{ if (t.getAttribute('aria-selected') === 'true') activeIdx = i; }});
            navButtons.forEach((btn, i) => {{
                if (!btn) return;
                btn.classList.toggle('nav-active', i === activeIdx);
            }});
        }}

        if (pending !== null) {{
            const tabEls = getTabs();
            if (tabEls[pending]) tabEls[pending].click();
            // React Aria's selection-state update isn't guaranteed to be
            // reflected in the DOM synchronously within this same tick, so
            // re-check shortly after in addition to the immediate call.
            setTimeout(highlightActive, 50);
        }}
        highlightActive();

        const tabList = doc.querySelector('[role="tablist"]');
        if (tabList) {{
            // components.html re-creates this script's iframe on every
            // rerun (not just sidebar clicks), which kills any observer
            // from the previous iframe -- a persisted boolean flag on
            // tabList would then wrongly skip re-attaching a replacement,
            // silently leaving no observer alive after the very first
            // unrelated rerun (this happened in testing). Always replace
            // it instead, using the tabList node itself (which *is*
            // preserved across reruns) to hold the current instance so we
            // can disconnect the stale one first.
            if (tabList._navObserver) {{
                tabList._navObserver.disconnect();
            }}
            // No attributeFilter: React Aria toggles both aria-selected and
            // data-selected on tab change, and only watching one of them
            // proved to miss updates in testing.
            const obs = new MutationObserver(highlightActive);
            obs.observe(tabList, {{ attributes: true, subtree: true }});
            tabList._navObserver = obs;
        }}
    }})();
    </script>
    """,
    height=0,
)
