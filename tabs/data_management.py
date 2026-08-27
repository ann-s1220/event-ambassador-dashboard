import streamlit as st
from streamlit_authenticator import Hasher

import db


def _current_user_is_admin(auth_config: dict) -> bool:
    username = st.session_state.get("username")
    user = auth_config.get("credentials", {}).get("usernames", {}).get(username, {})
    return "admin" in (user.get("roles") or [])


def _add_teammate_section(auth_config: dict):
    """Admin-only account creation -- deliberately the *only* way a new
    login gets created (no public sign-up flow exists anywhere in the
    app). New teammates get a temporary password and `must_change_password`
    set, which app.py checks right after login to force them onto
    streamlit-authenticator's own reset_password widget before they see
    anything else."""
    st.subheader("Add teammate")
    st.caption(
        "Creates a login for a new team member. Give them the username and temporary "
        "password directly -- they'll be required to set their own password the first "
        "time they sign in."
    )

    notice = st.session_state.pop("_new_teammate_notice", None)
    if notice:
        st.success(
            f"Added **{notice['name']}** -- share the username **{notice['username']}** and the "
            "temporary password you just set with them directly."
        )

    with st.form("add_teammate_form", clear_on_submit=True):
        name = st.text_input("Name")
        username = st.text_input(
            "Username / email", help="What they'll type to log in -- typically their email."
        )
        temp_password = st.text_input("Temporary password", type="password")
        submitted = st.form_submit_button("Add teammate", type="primary")

    if not submitted:
        return

    name = name.strip()
    username = username.strip().lower()
    if not name or not username or not temp_password:
        st.error("Name, username/email, and temporary password are all required.")
        return

    usernames = auth_config.setdefault("credentials", {}).setdefault("usernames", {})
    if username in usernames:
        st.error(
            f"'{username}' already has an account. To reset an existing user's password, "
            "use `python scripts/manage_users.py add-user` from the command line."
        )
        return

    usernames[username] = {
        "name": name,
        "email": username,
        "password": Hasher.hash(temp_password),
        "must_change_password": True,
    }
    st.session_state["_save_auth_config"]()
    st.session_state["_new_teammate_notice"] = {"username": username, "name": name}
    st.rerun()


@st.dialog("Confirm delete")
def _confirm_delete_teammate_dialog(username: str, name: str):
    # Belt-and-suspenders on top of the disabled button for this row: the
    # button can't fire for the currently logged-in account, but this
    # closes off any path that might otherwise let someone lock themselves
    # out (e.g. a stale button reference from before a role/username
    # change earlier in the same session).
    if username == st.session_state.get("username"):
        st.error("You can't remove the account you're currently logged in as.")
        if st.button("Close"):
            st.rerun()
        return

    st.write(f"You are about to remove **{name}**'s access.")
    st.markdown("Are you sure you want to remove this teammate? **This cannot be undone.**")
    c1, c2 = st.columns(2)
    if c1.button("Cancel"):
        st.rerun()
    if c2.button("Confirm delete", type="primary"):
        auth_config = st.session_state["_auth_config"]
        auth_config["credentials"]["usernames"].pop(username, None)
        st.session_state["_save_auth_config"]()
        st.session_state["_teammate_deleted_notice"] = name
        st.rerun()


def _teammates_list_section(auth_config: dict):
    """Lists every teammate account -- each with an inline "Remove" action
    -- and flags any pending admin-mediated password-reset request --
    submitted via the "Forgot password?" link on the login screen (see
    auth_helpers.py); this app has no outbound-email setup, so the request
    lands here instead of resetting anything automatically. Rendered as a
    manual row-per-teammate loop rather than st.dataframe, since a
    dataframe has no way to embed an interactive button inside a row.
    Setting a new temporary password below follows the same manual
    hand-off as "Add teammate" above: the admin picks a temporary password
    and shares it with the teammate directly, and must_change_password
    forces them to replace it on their next login."""
    st.subheader("Teammates")
    usernames = auth_config.get("credentials", {}).get("usernames", {})
    if not usernames:
        st.caption("No teammates yet.")
        return

    def _status(user: dict) -> str:
        if user.get("password_reset_requested"):
            return "Password reset requested"
        if user.get("must_change_password"):
            return "Must set password"
        return "Active"

    deleted_notice = st.session_state.pop("_teammate_deleted_notice", None)
    if deleted_notice:
        st.success(f"Removed **{deleted_notice}**'s access.")

    current_username = st.session_state.get("username")
    col_widths = [2, 2, 1.5, 2, 1]
    for col, label in zip(st.columns(col_widths), ["Name", "Username", "Roles", "Status", ""]):
        col.markdown(f"**{label}**")

    for username, user in usernames.items():
        name_col, username_col, roles_col, status_col, action_col = st.columns(col_widths)
        name_col.write(user.get("name", ""))
        username_col.write(username)
        roles_col.write(", ".join(user.get("roles") or []) or "—")
        status_col.write(_status(user))
        is_self = username == current_username
        if action_col.button(
            "Remove",
            key=f"remove_teammate_{username}",
            disabled=is_self,
            help="You can't remove the account you're currently logged in as." if is_self else None,
        ):
            _confirm_delete_teammate_dialog(username, user.get("name") or username)

    notice = st.session_state.pop("_teammate_password_reset_notice", None)
    if notice:
        st.success(
            f"Set a new temporary password for **{notice}** -- share it with them "
            "directly. They'll be required to set their own password on next login."
        )

    st.markdown("**Set a new temporary password**")
    target_username = st.selectbox(
        "Teammate",
        options=list(usernames.keys()),
        format_func=lambda u: (
            f"{usernames[u].get('name', u)} ({u})"
            + (" — password reset requested" if usernames[u].get("password_reset_requested") else "")
        ),
        key="teammate_password_reset_select",
    )
    with st.form("teammate_password_reset_form", clear_on_submit=True):
        new_temp_password = st.text_input("New temporary password", type="password")
        submitted = st.form_submit_button("Set temporary password", type="primary")
    if submitted:
        if not new_temp_password:
            st.error("Enter a temporary password.")
        else:
            target = usernames[target_username]
            target["password"] = Hasher.hash(new_temp_password)
            target["must_change_password"] = True
            target.pop("password_reset_requested", None)
            target.pop("password_reset_requested_at", None)
            st.session_state["_save_auth_config"]()
            st.session_state["_teammate_password_reset_notice"] = target.get("name", target_username)
            st.rerun()


@st.dialog("Confirm member erasure")
def _confirm_delete_dialog(member_id: int):
    preview = db.get_anonymization_preview(st.session_state["_conn"], member_id)
    st.write(f"You are about to erase **{preview['name']}** ({preview['email']}).")
    st.markdown("This is **irreversible**. It will:")
    st.markdown(
        f"- Unlink them from **{preview['attendance_rows_to_unlink']}** attendance record(s) "
        "(records stay, member_id set to NULL)"
    )
    st.markdown(
        f"- Unlink them from **{preview['feedback_rows_to_unlink']}** feedback record(s) "
        "(records stay, member_id set to NULL)"
    )
    if preview["ambassador_row_deleted"]:
        st.markdown(
            f"- Unlink their ambassador attribution from **{preview['referral_rows_to_unlink']}** "
            "referred attendance row(s)"
        )
        st.markdown(
            f"- Unlink their ambassador attribution from **{preview['social_post_rows_to_unlink']}** "
            "social post row(s)"
        )
        st.markdown("- Delete their ambassador roster row")
    st.markdown("- Delete their member row entirely")
    st.markdown("- Log a generic, non-personal entry to the deletion log")

    c1, c2 = st.columns(2)
    if c1.button("Cancel"):
        st.rerun()
    if c2.button("Confirm erasure", type="primary"):
        db.anonymize_member(st.session_state["_conn"], member_id)
        st.session_state["_deleted_notice"] = preview["name"]
        st.rerun()


def render(conn):
    st.header("Data management (GDPR)")
    st.session_state["_conn"] = conn

    if st.session_state.get("_deleted_notice"):
        st.success(f"Erased member '{st.session_state.pop('_deleted_notice')}'.")

    st.subheader("Find a member")
    query = st.text_input("Search by name or email")
    members = db.get_members_df(conn)
    if query:
        q = query.lower()
        # regex=False: plain substring search -- pandas treats the pattern
        # as regex by default, so an unescaped `[`, `(`, etc. typed into
        # the search box would otherwise raise an uncaught regex error.
        results = members[
            members["name"].str.lower().str.contains(q, na=False, regex=False)
            | members["email"].str.lower().str.contains(q, na=False, regex=False)
        ]
    else:
        results = members

    if results.empty:
        st.caption("No matching members.")
    else:
        st.dataframe(
            results[["member_id", "name", "email", "member_type", "is_ambassador"]],
            width="stretch",
        )
        member_id = st.selectbox(
            "Select a member to erase",
            options=[None] + list(results["member_id"]),
            format_func=lambda mid: "-- select --" if mid is None else
            f"{results.loc[results.member_id == mid, 'name'].iloc[0]} "
            f"({results.loc[results.member_id == mid, 'email'].iloc[0]})",
        )
        if member_id is not None:
            if st.button("Delete member (GDPR erasure)", type="primary"):
                _confirm_delete_dialog(int(member_id))

    st.divider()
    st.subheader("Deletion log")
    st.caption("Timestamp and generic action description only -- no personal data.")
    st.dataframe(db.get_deletion_log_df(conn)[["timestamp", "action_description"]], width="stretch")

    st.divider()
    st.subheader("Edit log")
    st.caption(
        "Hard deletes of mistaken attendance/feedback/social-post entries (Tabs 1-3) -- "
        "separate from the deletion log above, which is GDPR erasures only."
    )
    st.dataframe(db.get_edit_log_df(conn)[["timestamp", "action_description"]], width="stretch")

    auth_config = st.session_state.get("_auth_config")
    if auth_config is not None and _current_user_is_admin(auth_config):
        st.divider()
        _add_teammate_section(auth_config)
        st.divider()
        _teammates_list_section(auth_config)
