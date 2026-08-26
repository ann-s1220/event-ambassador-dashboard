import json
import os

import streamlit as st
import streamlit.components.v1 as components
import yaml
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth
from streamlit_authenticator.utilities import CredentialsError, LoginError, ResetError

import db
from style import get_css
from tabs import ambassadors, attendance, data_management, feedback

st.set_page_config(page_title="Event & Ambassador Dashboard", layout="wide")

CONFIG_PATH = "config.yaml"

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

if "dark_mode" not in st.session_state:
    st.session_state["dark_mode"] = True

# Login form and any not-yet-authenticated messaging need the theme too,
# so this first injection uses whatever dark_mode currently holds (the
# default, since the toggle itself only exists in the sidebar below,
# which is gated behind a successful login).
st.markdown(get_css(st.session_state["dark_mode"]), unsafe_allow_html=True)

st.title("Event & Ambassador Dashboard")

if not os.path.exists(CONFIG_PATH):
    st.error(
        f"No `{CONFIG_PATH}` found -- this app has no authorized users yet. "
        "Create the first one by running:\n\n"
        "```\npython scripts/manage_users.py add-user\n```"
    )
    st.stop()

def save_auth_config() -> None:
    """Persist auth_config back to config.yaml. Needed because we hand
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

try:
    authenticator.login()
except LoginError as e:
    st.error(str(e))
    st.stop()

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

with st.sidebar:
    st.markdown(f"Signed in as **{st.session_state.get('name')}**")
    authenticator.logout("Logout", "sidebar")
    st.divider()
    st.markdown("**Navigate**")
    for i, name in enumerate(SECTION_NAMES):
        if st.button(name, key=f"nav_{name}", width="stretch"):
            st.session_state["_pending_tab_click"] = i
            st.rerun()
    st.divider()
    st.toggle("Dark mode", key="dark_mode")

st.markdown(get_css(st.session_state["dark_mode"]), unsafe_allow_html=True)

db.init_db()
conn = db.get_connection()

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
