"""Login-screen helpers shared by app.py on both `main` and `demo`:

- `render_login_form` accepts a username *or* email in the same field.
  streamlit-authenticator's own `login()` widget only ever matches its
  `credentials.usernames` dict by key, with no email fallback and no hook
  to add one -- the widget renders the form and authenticates in a single
  call. Supporting "log in with email" therefore means re-rendering that
  form ourselves (mirroring `Authenticate.login()`'s own implementation:
  the pre-render cookie check, the same sleep, the same post-submit
  cookie set) with an identifier-resolution step in front of the
  library's `authentication_controller.login()`, rather than anything
  the library exposes as a parameter.
- `render_forgot_password_section` is an admin-mediated password-reset
  request, in place of the library's own `forgot_password()` widget.
  That widget resets the password immediately and hands the new
  plaintext value back on the same, unauthenticated screen -- reasonable
  when `send_email=True` mails it to a verified inbox, but this app has
  no outbound-email setup, and without email delivery that same value
  would just be shown directly on the public login page to anyone who
  types in a valid username, with no proof of identity at all. Flagging
  the account for an admin to review instead (see the "Teammates"
  section on the Data management (GDPR) tab) keeps the human
  verification step that email would otherwise provide.
"""
import time
from datetime import datetime, timezone

import streamlit as st


def resolve_login_identifier(auth_config: dict, identifier: str) -> str | None:
    """Match a login-form entry against every account's username OR email
    (case-insensitive), so one field accepts either. Returns the actual
    username key streamlit-authenticator's credentials dict is keyed on,
    or None if nothing matches."""
    identifier = (identifier or "").strip().lower()
    if not identifier:
        return None
    usernames = auth_config.get("credentials", {}).get("usernames", {})
    if identifier in usernames:
        return identifier
    for username, user in usernames.items():
        if (user.get("email") or "").strip().lower() == identifier:
            return username
    return None


def render_login_form(authenticator, auth_config: dict) -> None:
    """Renders a login form equivalent to `authenticator.login()`, except
    the single identifier field is resolved against both username and
    email before being handed to streamlit-authenticator's own login
    logic. Reaches into `authenticator.authentication_controller` /
    `.cookie_controller` -- the same public attributes `Authenticate.login()`
    itself calls -- since there's no supported way to intercept the
    entered value from inside that all-in-one widget call."""
    if st.session_state.get("authentication_status"):
        return

    token = authenticator.cookie_controller.get_cookie()
    if token:
        authenticator.authentication_controller.login(token=token)
    # Matches streamlit-authenticator's own pre-login pause (params.PRE_LOGIN_SLEEP_TIME).
    time.sleep(0.7)
    if st.session_state.get("authentication_status"):
        return

    with st.form("Login", clear_on_submit=False):
        st.subheader("Login")
        identifier = st.text_input("Username or email", autocomplete="off")
        password = st.text_input("Password", type="password", autocomplete="off")
        submitted = st.form_submit_button("Login")

    if not submitted:
        return

    resolved_username = resolve_login_identifier(auth_config, identifier) or identifier.strip().lower()
    if authenticator.authentication_controller.login(resolved_username, password):
        authenticator.cookie_controller.set_cookie()


def render_forgot_password_section(auth_config: dict, save_auth_config) -> None:
    """Admin-mediated password reset request. Flags the matched account
    with `password_reset_requested` (+ a timestamp) for an admin to see
    and act on from the Data management (GDPR) tab's teammate list --
    never resets or reveals a password itself. Responds identically
    whether or not the identifier matched anything, so this form can't be
    used to enumerate valid usernames/emails."""
    if st.session_state.get("authentication_status"):
        return

    with st.expander("Forgot password?"):
        with st.form("forgot_password_form", clear_on_submit=True):
            identifier = st.text_input("Username or email", key="forgot_password_identifier")
            submitted = st.form_submit_button("Request password reset")

        if not submitted:
            return
        if not identifier.strip():
            st.warning("Enter a username or email.")
            return

        matched_username = resolve_login_identifier(auth_config, identifier)
        if matched_username:
            usernames = auth_config["credentials"]["usernames"]
            usernames[matched_username]["password_reset_requested"] = True
            usernames[matched_username]["password_reset_requested_at"] = (
                datetime.now(timezone.utc).isoformat(timespec="seconds")
            )
            save_auth_config()
        st.info(
            "If that account exists, an admin has been notified and will reach out "
            "with a new temporary password."
        )


def clear_pending_reset_notice_on_logout(*_args, **_kwargs) -> None:
    """logout() callback: without this, `render_pending_reset_notice`'s
    "already checked" flag would survive a logout and silently suppress the
    notice for the next person who logs into the same browser tab -- most
    often the same admin logging back in, but a different admin taking
    over the tab would be silently skipped too."""
    st.session_state.pop("_pending_reset_checked_for", None)
    st.session_state.pop("_pending_reset_dialog_open", None)


@st.dialog("Pending password reset requests")
def _pending_reset_dialog(count: int, data_management_index: int) -> None:
    plural = "" if count == 1 else "s"
    st.write(f"You have **{count}** pending password reset request{plural}.")
    st.caption(
        "A teammate used \"Forgot password?\" on the login screen. Review the "
        "Teammates list on the Data management (GDPR) tab and set a new temporary "
        "password for them there."
    )
    c1, c2 = st.columns(2)
    if c1.button("Dismiss"):
        st.session_state["_pending_reset_dialog_open"] = False
        st.rerun()
    if c2.button("Go to Manage Teammates", type="primary"):
        st.session_state["_pending_reset_dialog_open"] = False
        st.session_state["_pending_tab_click"] = data_management_index
        st.rerun()


def render_pending_reset_notice(auth_config: dict, is_admin: bool, section_names: list) -> None:
    """Pops up (once per login, not once per rerun/tab click) to tell an admin
    about any outstanding admin-mediated password-reset requests -- see
    `render_forgot_password_section` above for how those get flagged.

    A login triggers more than one script rerun in quick succession (the
    cookie set right after a successful login causes an extra one), and
    `@st.dialog` only stays open on a rerun that actually re-calls the
    decorated function -- so gating that call on a single "already shown"
    flag flipped True on the very first rerun meant the second, automatic
    rerun skipped the call and silently closed the dialog before it was
    ever visible (confirmed by reproducing it with logging). Splitting
    "have we checked yet this login" from "should the dialog currently be
    open" fixes it: the pending-request check itself still runs once per
    login (scoped to `st.session_state["username"]`, and cleared on
    logout below so a fresh login -- same admin or a different one -- in
    the same browser tab re-triggers it), but once open, the dialog
    function is re-called on every rerun for as long as
    `_pending_reset_dialog_open` stays True, which only its own Dismiss /
    "Go to Manage Teammates" buttons flip to False."""
    if not is_admin:
        return

    current_username = st.session_state.get("username")
    if st.session_state.get("_pending_reset_checked_for") != current_username:
        st.session_state["_pending_reset_checked_for"] = current_username
        usernames = auth_config.get("credentials", {}).get("usernames", {})
        pending_count = sum(1 for user in usernames.values() if user.get("password_reset_requested"))
        st.session_state["_pending_reset_count"] = pending_count
        st.session_state["_pending_reset_dialog_open"] = pending_count > 0

    if st.session_state.get("_pending_reset_dialog_open"):
        _pending_reset_dialog(
            st.session_state["_pending_reset_count"], section_names.index("Data management (GDPR)")
        )
