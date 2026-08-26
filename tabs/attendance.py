import altair as alt
import pandas as pd
import streamlit as st

import db
from csv_import import (
    NONE_CHOICE, SOURCE_VALUES, STATUS_VALUES, TARGET_FIELDS,
    import_attendance_csv, preview_members, suggest_column_map, suggest_source_map,
    suggest_status_map, unique_values,
)
from excel_import import (
    MEMBER_REQUIRED_FIELDS, MEMBER_TARGET_FIELDS, MEMBER_TYPE_VALUES,
    import_members_excel, suggest_member_column_map, suggest_member_type_map,
)

SYNC_REMOVAL_THRESHOLD = 0.5

# Brand accents (see style.py) -- kept identical in light/dark mode; the
# chart's text/background follow the mode via the same CSS that already
# themes st.bar_chart/st.line_chart, since Altair renders through the same
# Vega-Lite component.
PIE_COLORS = {"attended": "#7A5C8E", "did not attend": "#D98F6E"}

SOURCE_LABELS = {"social_media": "Social media", "student_ambassador": "Student ambassador", "other": "Other"}
# Third color is a deeper rose (rather than the pale --pink highlight) so it
# still reads clearly against both the light and dark chart background.
SOURCE_COLORS = {"social_media": "#7A5C8E", "student_ambassador": "#D98F6E", "other": "#B5677A"}

# Sized so slice labels sit well outside the arc (avoids overlap/crowding
# between adjacent labels) with room to spare before the chart's edge.
PIE_SIZE = 320
PIE_OUTER_RADIUS = 75
PIE_LABEL_RADIUS = 118


def _attendance_pie_chart(att: pd.DataFrame, title: str):
    """Pie chart of attended vs. did-not-attend for the given attendance
    rows, with percentage + raw count labels. Returns None if empty."""
    if att.empty:
        return None
    counts = att["status"].value_counts()
    total = int(counts.sum())
    rows = []
    for status in ["attended", "did not attend"]:
        count = int(counts.get(status, 0))
        if count == 0:
            continue
        pct = round(100 * count / total) if total else 0
        rows.append({"status": status, "count": count, "label": f"{pct}% ({count})"})
    chart_df = pd.DataFrame(rows)

    base = alt.Chart(chart_df).encode(
        theta=alt.Theta("count:Q", stack=True),
        color=alt.Color(
            "status:N",
            scale=alt.Scale(domain=list(PIE_COLORS.keys()), range=list(PIE_COLORS.values())),
            legend=alt.Legend(title=None, orient="bottom"),
        ),
    )
    arc = base.mark_arc(outerRadius=PIE_OUTER_RADIUS)
    labels = base.mark_text(radius=PIE_LABEL_RADIUS, size=12).encode(text="label:N")
    return (
        (arc + labels)
        .properties(
            title=title, width=PIE_SIZE, height=PIE_SIZE, background="transparent",
            padding={"left": 30, "right": 30, "top": 15, "bottom": 15},
        )
    )


def _attendance_stat_line(att: pd.DataFrame) -> str:
    counts = att["status"].value_counts()
    total = int(counts.sum())
    parts = []
    for status in ["attended", "did not attend"]:
        count = int(counts.get(status, 0))
        pct = round(100 * count / total) if total else 0
        label = "Attended" if status == "attended" else "Did not attend"
        parts.append(f"**{label}:** {pct}% ({count})")
    return " &nbsp;&nbsp;|&nbsp;&nbsp; ".join(parts)


def _source_pie_chart(att: pd.DataFrame, title: str):
    """Pie chart of attendance source (social media / student ambassador /
    other), with percentage + raw count labels. Returns None if empty."""
    if att.empty:
        return None
    counts = att["source_type"].value_counts()
    total = int(counts.sum())
    rows = []
    for source in SOURCE_LABELS:
        count = int(counts.get(source, 0))
        if count == 0:
            continue
        pct = round(100 * count / total) if total else 0
        rows.append({"source": SOURCE_LABELS[source], "count": count, "label": f"{pct}% ({count})"})
    chart_df = pd.DataFrame(rows)

    base = alt.Chart(chart_df).encode(
        theta=alt.Theta("count:Q", stack=True),
        color=alt.Color(
            "source:N",
            scale=alt.Scale(domain=list(SOURCE_LABELS.values()), range=list(SOURCE_COLORS.values())),
            legend=alt.Legend(title=None, orient="bottom"),
        ),
    )
    arc = base.mark_arc(outerRadius=PIE_OUTER_RADIUS)
    labels = base.mark_text(radius=PIE_LABEL_RADIUS, size=12).encode(text="label:N")
    return (
        (arc + labels)
        .properties(
            title=title, width=PIE_SIZE, height=PIE_SIZE, background="transparent",
            padding={"left": 30, "right": 30, "top": 15, "bottom": 15},
        )
    )


def _source_stat_line(att: pd.DataFrame) -> str:
    counts = att["source_type"].value_counts()
    total = int(counts.sum())
    parts = []
    for source, label in SOURCE_LABELS.items():
        count = int(counts.get(source, 0))
        pct = round(100 * count / total) if total else 0
        parts.append(f"**{label}:** {pct}% ({count})")
    return " &nbsp;&nbsp;|&nbsp;&nbsp; ".join(parts)


def _import_section(conn):
    st.subheader("Import Luma CSV export")
    events = db.get_events_df(conn)
    if events.empty:
        st.info("Add an event first (see the manual form below) before importing attendance.")
        return

    event_label = st.selectbox(
        "Event this export belongs to",
        options=events["event_id"],
        format_func=lambda eid: events.loc[events.event_id == eid, "name"].iloc[0]
        + " (" + events.loc[events.event_id == eid, "date"].iloc[0] + ")",
        key="import_event",
    )

    uploaded = st.file_uploader("CSV file", type=["csv"])
    if uploaded is None:
        return

    try:
        data = pd.read_csv(uploaded)
    except Exception as e:
        # Broad on purpose: this is a trust boundary (an arbitrary
        # uploaded file), and pandas/its parser raise several different
        # exception types for a malformed CSV -- none of which a user
        # needs to see, they just need to know the file didn't work.
        print(f"CSV import parse failure ({uploaded.name}): {e}")
        st.error("Couldn't read that file as a CSV. Please check the format and try again.")
        return
    st.caption(f"{len(data)} rows, {len(data.columns)} columns detected.")
    st.dataframe(data.head(5), width="stretch")

    st.markdown("**Map CSV columns to dashboard fields**")
    suggested = suggest_column_map(list(data.columns))
    column_map = {}
    cols = st.columns(2)
    for i, field in enumerate(TARGET_FIELDS):
        with cols[i % 2]:
            options = [NONE_CHOICE] + list(data.columns)
            default = suggested.get(field, NONE_CHOICE)
            idx = options.index(default) if default in options else 0
            column_map[field] = st.selectbox(field, options, index=idx, key=f"map_{field}")

    missing_required = [f for f in ("name", "email") if column_map[f] == NONE_CHOICE]
    if missing_required:
        st.warning(f"Map required field(s) before importing: {', '.join(missing_required)}")
        return

    value_maps = {}
    if column_map["status"] != NONE_CHOICE:
        raw_values = unique_values(data[column_map["status"]])
        suggestion = suggest_status_map(raw_values)
        st.markdown("**Map status values**")
        vm = {}
        for v in raw_values:
            vm[v] = st.selectbox(
                f"'{v}' ->", STATUS_VALUES,
                index=STATUS_VALUES.index(suggestion.get(v, "attended")),
                key=f"status_val_{v}",
            )
        value_maps["status"] = vm

    if column_map["source_type"] != NONE_CHOICE:
        raw_values = unique_values(data[column_map["source_type"]])
        suggestion = suggest_source_map(raw_values)
        st.markdown("**Map source values**")
        vm = {}
        for v in raw_values:
            vm[v] = st.selectbox(
                f"'{v}' ->", SOURCE_VALUES,
                index=SOURCE_VALUES.index(suggestion.get(v, "other")),
                key=f"source_val_{v}",
            )
        value_maps["source_type"] = vm

    sync_mode = st.checkbox(
        "Flag members missing from this list for removal",
        value=False,
        key="sync_mode",
        help=(
            "Compares every member currently in the system (however they were added) against "
            "the emails in this file. Anyone not in the file is flagged for removal."
        ),
    )

    signature = (
        uploaded.name, uploaded.size,
        tuple(sorted(column_map.items())),
        repr(sorted((k, tuple(sorted(v.items()))) for k, v in value_maps.items())),
        event_label, sync_mode,
    )

    if st.button("Preview import", type="primary"):
        st.session_state.pop("import_sync_error", None)
        st.session_state.pop("import_preview", None)
        classified = preview_members(conn, data, column_map)
        to_remove = []
        if sync_mode:
            members = db.get_members_df(conn)
            missing = members[~members["email"].str.lower().isin(classified["file_emails"])]
            to_remove = missing[["member_id", "name", "email"]].to_dict("records")
            total_members = len(members)
            removal_fraction = (len(to_remove) / total_members) if total_members else 0.0
            if removal_fraction > SYNC_REMOVAL_THRESHOLD:
                st.session_state["import_sync_error"] = (
                    f"This file would remove {removal_fraction:.0%} of members, which exceeds the "
                    f"{SYNC_REMOVAL_THRESHOLD:.0%} safety threshold. Please check that you uploaded "
                    "the correct file."
                )
                st.session_state["import_sync_error_sig"] = signature
                st.rerun()
        st.session_state["import_preview"] = {
            "signature": signature,
            "to_create": classified["to_create"],
            "to_update": classified["to_update"],
            "to_remove": to_remove,
            "sync_mode": sync_mode,
            "committed_create_update": False,
        }
        st.rerun()

    sync_error = st.session_state.get("import_sync_error")
    if sync_error and st.session_state.get("import_sync_error_sig") == signature:
        st.error(sync_error)
        return

    preview = st.session_state.get("import_preview")
    if not preview or preview["signature"] != signature:
        return

    st.subheader("Preview")
    st.write(
        f"**{len(preview['to_create'])}** member(s) to create, "
        f"**{len(preview['to_update'])}** to update."
    )
    with st.expander(f"Members to create ({len(preview['to_create'])})"):
        st.dataframe(pd.DataFrame(preview["to_create"], columns=["name", "email"]), width="stretch")
    with st.expander(f"Members to update ({len(preview['to_update'])})"):
        st.dataframe(pd.DataFrame(preview["to_update"], columns=["name", "email"]), width="stretch")

    if preview["committed_create_update"]:
        st.success("Create/update already applied for this preview.")
    elif st.button("Confirm create/update", type="primary", key="confirm_create_update"):
        summary = import_attendance_csv(conn, data, column_map, value_maps, event_label)
        st.session_state["import_preview"]["committed_create_update"] = True
        st.success(
            f"Members created: {summary['members_created']}, updated: {summary['members_updated']}. "
            f"Attendance created: {summary['attendance_created']}, "
            f"skipped as duplicate: {summary['attendance_skipped_duplicate']}."
        )
        if summary["rows_skipped_no_email"]:
            st.warning(f"{summary['rows_skipped_no_email']} row(s) skipped -- no email present.")
        if summary["unmatched_ambassador_names"]:
            st.warning(
                "Referring ambassador name(s) not found in roster: "
                + ", ".join(sorted(summary["unmatched_ambassador_names"]))
            )
        st.rerun()

    if preview["sync_mode"] and preview["to_remove"]:
        st.divider()
        st.error(
            f"**{len(preview['to_remove'])} member(s) are missing from this file and flagged for "
            "removal.** Review the list below -- this action is irreversible."
        )
        st.dataframe(
            pd.DataFrame(preview["to_remove"])[["name", "email"]], width="stretch"
        )
        ack_key = f"removal_ack_{hash(signature)}"
        ack = st.checkbox(
            "I have reviewed this list and confirm these members should be permanently anonymized and removed.",
            key=ack_key,
        )
        if st.button(
            "Confirm removal (irreversible)", type="primary", key="confirm_removal", disabled=not ack
        ):
            for m in preview["to_remove"]:
                db.anonymize_member(conn, m["member_id"])
            st.success(f"Removed {len(preview['to_remove'])} member(s).")
            del st.session_state["import_preview"]
            st.rerun()


def _excel_import_section(conn):
    """Bulk member create/update from an Excel file, matched by email.
    Deliberately member-only -- unlike the Luma CSV import above, this
    never touches attendance. Shares the same column-mapping ->
    preview -> confirm shape, and the sync/removal safety threshold, as
    that import; session-state keys are namespaced with an `excel_`
    prefix so the two imports don't collide when both are used in the
    same session."""
    st.subheader("Import members from Excel")
    uploaded = st.file_uploader("Excel file (.xlsx)", type=["xlsx"], key="excel_member_file")
    if uploaded is None:
        return

    try:
        data = pd.read_excel(uploaded)
    except Exception as e:
        # Broad on purpose -- see the CSV import above: an uploaded file
        # is a trust boundary, and a malformed/renamed file can fail in
        # any of several ways (bad zip, bad XML, wrong sheet structure).
        print(f"Excel member import parse failure ({uploaded.name}): {e}")
        st.error("Couldn't read that file as an Excel (.xlsx) file. Please check the format and try again.")
        return
    st.caption(f"{len(data)} rows, {len(data.columns)} columns detected.")
    st.dataframe(data.head(5), width="stretch")

    st.markdown("**Map Excel columns to member fields**")
    suggested = suggest_member_column_map(list(data.columns))
    column_map = {}
    cols = st.columns(2)
    for i, field in enumerate(MEMBER_TARGET_FIELDS):
        with cols[i % 2]:
            options = [NONE_CHOICE] + list(data.columns)
            default = suggested.get(field, NONE_CHOICE)
            idx = options.index(default) if default in options else 0
            column_map[field] = st.selectbox(field, options, index=idx, key=f"excel_map_{field}")

    missing_required = [f for f in MEMBER_REQUIRED_FIELDS if column_map[f] == NONE_CHOICE]
    if missing_required:
        st.warning(f"Map required field(s) before importing: {', '.join(missing_required)}")
        return

    member_type_map = {}
    if column_map["member_type"] != NONE_CHOICE:
        raw_values = unique_values(data[column_map["member_type"]])
        suggestion = suggest_member_type_map(raw_values)
        st.markdown("**Map member type values**")
        for v in raw_values:
            member_type_map[v] = st.selectbox(
                f"'{v}' ->", MEMBER_TYPE_VALUES,
                index=MEMBER_TYPE_VALUES.index(suggestion.get(v, "non-student")),
                key=f"excel_type_val_{v}",
            )

    sync_mode = st.checkbox(
        "Flag members missing from this file for removal",
        value=False,
        key="excel_sync_mode",
        help=(
            "Compares every member currently in the system (however they were added) against "
            "the emails in this file. Anyone not in the file is flagged for removal."
        ),
    )

    signature = (
        uploaded.name, uploaded.size,
        tuple(sorted(column_map.items())),
        repr(sorted(member_type_map.items())),
        sync_mode,
    )

    if st.button("Preview import", type="primary", key="excel_preview_btn"):
        st.session_state.pop("excel_import_sync_error", None)
        st.session_state.pop("excel_import_preview", None)
        classified = preview_members(conn, data, column_map)
        to_remove = []
        if sync_mode:
            members = db.get_members_df(conn)
            missing = members[~members["email"].str.lower().isin(classified["file_emails"])]
            to_remove = missing[["member_id", "name", "email"]].to_dict("records")
            total_members = len(members)
            removal_fraction = (len(to_remove) / total_members) if total_members else 0.0
            if removal_fraction > SYNC_REMOVAL_THRESHOLD:
                st.session_state["excel_import_sync_error"] = (
                    f"This file would remove {removal_fraction:.0%} of members, which exceeds the "
                    f"{SYNC_REMOVAL_THRESHOLD:.0%} safety threshold. Please check that you uploaded "
                    "the correct file."
                )
                st.session_state["excel_import_sync_error_sig"] = signature
                st.rerun()
        st.session_state["excel_import_preview"] = {
            "signature": signature,
            "to_create": classified["to_create"],
            "to_update": classified["to_update"],
            "to_remove": to_remove,
            "sync_mode": sync_mode,
            "committed": False,
        }
        st.rerun()

    sync_error = st.session_state.get("excel_import_sync_error")
    if sync_error and st.session_state.get("excel_import_sync_error_sig") == signature:
        st.error(sync_error)
        return

    preview = st.session_state.get("excel_import_preview")
    if not preview or preview["signature"] != signature:
        return

    st.subheader("Preview")
    st.write(
        f"**{len(preview['to_create'])}** member(s) to create, "
        f"**{len(preview['to_update'])}** to update."
    )
    with st.expander(f"Members to create ({len(preview['to_create'])})"):
        st.dataframe(pd.DataFrame(preview["to_create"], columns=["name", "email"]), width="stretch")
    with st.expander(f"Members to update ({len(preview['to_update'])})"):
        st.dataframe(pd.DataFrame(preview["to_update"], columns=["name", "email"]), width="stretch")

    if preview["committed"]:
        st.success("Create/update already applied for this preview.")
    elif st.button("Confirm create/update", type="primary", key="excel_confirm_create_update"):
        summary = import_members_excel(conn, data, column_map, member_type_map)
        st.session_state["excel_import_preview"]["committed"] = True
        st.success(f"Members created: {summary['members_created']}, updated: {summary['members_updated']}.")
        if summary["rows_skipped_no_email"]:
            st.warning(f"{summary['rows_skipped_no_email']} row(s) skipped -- no email present.")
        st.rerun()

    if preview["sync_mode"] and preview["to_remove"]:
        st.divider()
        st.error(
            f"**{len(preview['to_remove'])} member(s) are missing from this file and flagged for "
            "removal.** Review the list below -- this action is irreversible."
        )
        st.dataframe(pd.DataFrame(preview["to_remove"])[["name", "email"]], width="stretch")
        ack_key = f"excel_removal_ack_{hash(signature)}"
        ack = st.checkbox(
            "I have reviewed this list and confirm these members should be permanently anonymized and removed.",
            key=ack_key,
        )
        if st.button(
            "Confirm removal (irreversible)", type="primary", key="excel_confirm_removal", disabled=not ack
        ):
            for m in preview["to_remove"]:
                db.anonymize_member(conn, m["member_id"])
            st.success(f"Removed {len(preview['to_remove'])} member(s).")
            del st.session_state["excel_import_preview"]
            st.rerun()


@st.dialog("Confirm delete")
def _confirm_delete_event_dialog(event_id: int, label: str):
    conn = st.session_state["_conn"]
    preview = db.get_event_deletion_preview(conn, event_id)
    st.write(f"You are about to delete the event: **{label}**.")
    st.markdown("This is **irreversible**. It will also permanently delete:")
    st.markdown(f"- **{preview['attendance_rows_deleted']}** attendance record(s)")
    st.markdown(f"- **{preview['feedback_rows_deleted']}** feedback entry/entries")
    st.markdown(f"- **{preview['social_post_rows_deleted']}** social post(s)")
    st.markdown("Are you sure you want to delete this event? **This cannot be undone.**")
    c1, c2 = st.columns(2)
    if c1.button("Cancel"):
        st.rerun()
    if c2.button("Confirm delete", type="primary"):
        db.delete_event(conn, event_id)
        st.session_state["_event_deleted_notice"] = label
        st.rerun()


def _manual_form(conn):
    st.session_state["_conn"] = conn
    st.subheader("Add / edit a member and attendance record")
    events = db.get_events_df(conn)
    ambassadors = db.get_ambassadors_df(conn)

    lookup_email = st.text_input("Look up existing member by email to edit (leave blank to add new)", key="manual_lookup")
    existing = db.find_member_by_email(conn, lookup_email) if lookup_email else None
    if lookup_email and existing is None:
        st.caption("No existing member with that email -- fill the form to create one.")

    # member_type lives outside the form so the type-specific fields below
    # can show/hide immediately as it's changed, instead of only on submit.
    member_type = st.radio(
        "Member type", ["student", "non-student"],
        index=0 if (existing and existing["member_type"] == "student") else 1,
        horizontal=True,
        key="manual_member_type",
    )

    with st.form("manual_member_form", clear_on_submit=False):
        name = st.text_input("Name", value=existing["name"] if existing else "")
        email = st.text_input("Email", value=existing["email"] if existing else lookup_email)

        if member_type == "student":
            year_of_study = st.text_input(
                "Year of study", value=(existing["year_of_study"] if existing and existing["year_of_study"] else "")
            )
            degree = st.text_input(
                "Degree", value=(existing["degree"] if existing and existing["degree"] else "")
            )
            job_role, company = "", ""
            is_alumnus_choice = "No"
            st.caption("Alumnus status doesn't apply to current students.")
        else:
            job_role = st.text_input("Job role", value=(existing["job_role"] if existing and existing["job_role"] else ""))
            company = st.text_input("Company", value=(existing["company"] if existing and existing["company"] else ""))
            year_of_study, degree = "", ""
            alum_options = ["Unknown", "Yes", "No"]
            alum_default = "Unknown"
            if existing is not None and existing["is_alumnus"] is not None:
                alum_default = "Yes" if existing["is_alumnus"] else "No"
            is_alumnus_choice = st.selectbox("Alumnus?", alum_options, index=alum_options.index(alum_default))

        st.markdown("**Attendance record (optional)**")
        add_attendance = st.checkbox("Also add/update an attendance record for an event", value=False)
        event_id = None
        status = "attended"
        source_type = "other"
        referring_ambassador_id = None
        if add_attendance and not events.empty:
            event_id = st.selectbox(
                "Event", options=events["event_id"],
                format_func=lambda eid: events.loc[events.event_id == eid, "name"].iloc[0],
            )
            status = st.selectbox("Status", STATUS_VALUES)
            source_type = st.selectbox("Source", SOURCE_VALUES)
            if source_type == "student_ambassador" and not ambassadors.empty:
                amb_id = st.selectbox(
                    "Referring ambassador", options=ambassadors["ambassador_id"],
                    format_func=lambda aid: ambassadors.loc[ambassadors.ambassador_id == aid, "name"].iloc[0],
                )
                referring_ambassador_id = int(amb_id)

        submitted = st.form_submit_button("Save")

    if submitted:
        if not name or not email:
            st.error("Name and email are required.")
            return
        is_alumnus_val = None if is_alumnus_choice == "Unknown" else (is_alumnus_choice == "Yes")
        f_job_role, f_company, f_year, f_degree, f_is_alumnus = db.type_specific_fields(
            member_type, job_role or None, company or None, year_of_study or None, degree or None, is_alumnus_val
        )
        ambassador_match = db.find_ambassador_by_email(conn, email)

        # Re-check by email at submit time (not just the `existing` looked
        # up when the form was rendered) so a duplicate submit -- e.g. a
        # double-click, or typing an email that already exists -- updates
        # the just-created/matching row instead of crashing on the
        # members.email UNIQUE constraint.
        existing = db.find_member_by_email(conn, email) or existing

        if existing:
            conn.execute(
                """UPDATE members SET name=?, member_type=?, job_role=?, company=?,
                   year_of_study=?, degree=?, is_alumnus=?, is_ambassador=?, ambassador_id=?
                   WHERE member_id=?""",
                (
                    name, member_type, f_job_role, f_company, f_year, f_degree,
                    None if f_is_alumnus is None else int(f_is_alumnus),
                    1 if ambassador_match else existing["is_ambassador"],
                    ambassador_match["ambassador_id"] if ambassador_match else existing["ambassador_id"],
                    existing["member_id"],
                ),
            )
            member_id = existing["member_id"]
        else:
            cur = conn.execute(
                """INSERT INTO members (name, email, member_type, job_role, company,
                   year_of_study, degree, is_alumnus, is_ambassador, ambassador_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    name, email, member_type, f_job_role, f_company, f_year, f_degree,
                    None if f_is_alumnus is None else int(f_is_alumnus),
                    1 if ambassador_match else 0,
                    ambassador_match["ambassador_id"] if ambassador_match else None,
                ),
            )
            member_id = cur.lastrowid

        if ambassador_match is not None and ambassador_match["member_id"] is None:
            conn.execute(
                "UPDATE ambassadors SET member_id=? WHERE ambassador_id=?",
                (member_id, ambassador_match["ambassador_id"]),
            )

        if add_attendance and event_id is not None:
            dup = conn.execute(
                "SELECT attendance_id FROM attendance WHERE member_id=? AND event_id=?",
                (member_id, event_id),
            ).fetchone()
            if dup:
                conn.execute(
                    "UPDATE attendance SET status=?, source_type=?, referring_ambassador_id=? WHERE attendance_id=?",
                    (status, source_type, referring_ambassador_id, dup["attendance_id"]),
                )
            else:
                conn.execute(
                    """INSERT INTO attendance (member_id, event_id, status, source_type, referring_ambassador_id)
                       VALUES (?, ?, ?, ?, ?)""",
                    (member_id, event_id, status, source_type, referring_ambassador_id),
                )
        conn.commit()
        st.success(f"Saved member '{name}'.")
        st.rerun()

    with st.expander("Add / delete an event"):
        with st.form("add_event_form"):
            ev_name = st.text_input("Event name")
            ev_date = st.date_input("Date")
            ev_type = st.selectbox("Type", ["normal", "ambassador_workshop"])
            if st.form_submit_button("Add event"):
                if ev_name:
                    conn.execute(
                        "INSERT INTO events (name, date, type) VALUES (?, ?, ?)",
                        (ev_name, str(ev_date), ev_type),
                    )
                    conn.commit()
                    st.success(f"Added event '{ev_name}'.")
                    st.rerun()
                else:
                    st.error("Event name is required.")

        st.divider()
        st.markdown("**Delete an event**")
        st.caption(
            "Events don't support the anonymize-in-place erasure members/ambassadors get -- "
            "attendance, feedback, and social-post records all require an event, so deleting one "
            "permanently deletes every record tied to it too. You'll see exactly what before confirming."
        )

        if st.session_state.get("_event_deleted_notice"):
            st.success(f"Deleted event: {st.session_state.pop('_event_deleted_notice')}")

        if events.empty:
            st.caption("No events to delete.")
        else:
            delete_event_id = st.selectbox(
                "Select an event to delete",
                options=[None] + list(events["event_id"]),
                format_func=lambda eid: "-- select --" if eid is None else (
                    f"{events.loc[events.event_id == eid, 'name'].iloc[0]} "
                    f"({events.loc[events.event_id == eid, 'date'].iloc[0]})"
                ),
                key="event_delete_select",
            )
            if delete_event_id is not None:
                row = events.loc[events.event_id == delete_event_id].iloc[0]
                label = f"{row['name']} ({row['date']})"
                if st.button("Delete event", type="primary", key="event_delete_btn"):
                    _confirm_delete_event_dialog(int(delete_event_id), label)


def _summary_charts(conn):
    """Two stacked rows of pie-chart pairs: an "All events" row (constant,
    always aggregated across every event) on top, and a "By event" row
    below it, driven by a dropdown (defaulting to the most recent event)
    -- only that lower row updates when the dropdown changes. This is the
    first thing shown in the tab."""
    events = db.get_events_df(conn)
    attendance = db.get_attendance_df(conn)

    if events.empty:
        st.info("No events yet -- add one further down to start tracking attendance.")
        return

    st.markdown("**All events**")
    if attendance.empty:
        st.caption("No attendance records yet.")
    else:
        agg_c1, agg_c2 = st.columns(2)
        with agg_c1:
            st.altair_chart(_attendance_pie_chart(attendance, "Attendance rate"), use_container_width=False)
            st.caption(_attendance_stat_line(attendance))
        with agg_c2:
            st.altair_chart(_source_pie_chart(attendance, "Source breakdown"), use_container_width=False)
            st.caption(_source_stat_line(attendance))

    st.markdown("**By event**")
    events_by_date = events.sort_values("date", ascending=False)
    event_choice = st.selectbox(
        "Event", options=list(events_by_date["event_id"]),
        format_func=lambda eid: events.loc[events.event_id == eid, "name"].iloc[0]
        + " (" + events.loc[events.event_id == eid, "date"].iloc[0] + ")",
        key="view_event",
    )
    att = attendance[attendance.event_id == event_choice]
    if att.empty:
        st.caption("No attendance records for this event yet.")
    else:
        ev_c1, ev_c2 = st.columns(2)
        with ev_c1:
            st.altair_chart(_attendance_pie_chart(att, "Attendance rate"), use_container_width=False)
            st.caption(_attendance_stat_line(att))
        with ev_c2:
            st.altair_chart(_source_pie_chart(att, "Source breakdown"), use_container_width=False)
            st.caption(_source_stat_line(att))


def _members_list(conn):
    members = db.get_members_df(conn)
    events = db.get_events_df(conn)
    event_history = db.df(
        conn,
        """SELECT a.member_id, GROUP_CONCAT(DISTINCT e.name) AS events_attended
           FROM attendance a JOIN events e ON e.event_id = a.event_id
           WHERE a.status = 'attended' AND a.member_id IS NOT NULL
           GROUP BY a.member_id""",
    )
    members = members.merge(event_history, on="member_id", how="left")
    members["events_attended"] = members["events_attended"].fillna("")

    with st.expander("Members list", expanded=False):
        fcol1, fcol2, fcol3, fcol4 = st.columns(4)
        with fcol1:
            type_filter = st.multiselect(
                "Member type", ["student", "non-student"], default=["student", "non-student"],
                key="members_type_filter",
            )
        with fcol2:
            alum_filter = st.selectbox("Alumnus", ["All", "Yes", "No", "Unknown"], key="members_alum_filter")
        with fcol3:
            event_filter = st.selectbox(
                "Filter by event attended",
                options=["All events"] + list(events["event_id"]),
                format_func=lambda eid: "All events" if eid == "All events" else events.loc[events.event_id == eid, "name"].iloc[0],
                key="members_event_filter",
            )
        with fcol4:
            search = st.text_input(
                "Search all fields (name, email, type, role, company, degree, "
                "alumnus/ambassador status, events attended)",
                key="members_search",
            )

        filtered = members[members["member_type"].isin(type_filter)] if type_filter else members
        if alum_filter == "Yes":
            filtered = filtered[filtered["is_alumnus"] == 1]
        elif alum_filter == "No":
            filtered = filtered[filtered["is_alumnus"] == 0]
        elif alum_filter == "Unknown":
            filtered = filtered[filtered["is_alumnus"].isna()]
        if event_filter != "All events":
            attended_ids = {
                row["member_id"] for row in conn.execute(
                    "SELECT DISTINCT member_id FROM attendance WHERE status='attended' AND event_id=? AND member_id IS NOT NULL",
                    (event_filter,),
                ).fetchall()
            }
            filtered = filtered[filtered["member_id"].isin(attended_ids)]
        if search:
            s = search.lower()
            # One combined haystack per row -- name/email plus every other
            # searchable field (including events attended) -- rather than
            # a long chain of ORed str.contains calls, so "typing any part
            # of any of these fields" (including a boolean-ish field like
            # is_alumnus/is_ambassador, translated to words first) is a
            # single check instead of one branch per field.
            text_cols = ["name", "email", "member_type", "job_role", "company", "year_of_study", "degree", "events_attended"]
            haystack = filtered["name"].astype(str).str.lower()
            for col in text_cols[1:]:
                haystack = haystack + " " + filtered[col].fillna("").astype(str).str.lower()
            # is_alumnus: nullable (Yes/No/Unknown) -- include synonyms so
            # "alumni"/"alumnus" surface alumni the same way "yes" would.
            haystack = haystack + " " + filtered["is_alumnus"].map(
                {1: "alumnus alumni yes", 0: "no"}
            ).fillna("unknown")
            # is_ambassador: NOT NULL, so no unknown/NaN case to handle.
            haystack = haystack + " " + filtered["is_ambassador"].map({1: "ambassador yes", 0: "no"})

            # regex=False: this is meant as a plain substring search (per
            # the "partial, case-insensitive" description in the README),
            # and pandas treats str.contains's pattern as regex by default
            # -- an unescaped `[`, `(`, etc. in the search box would
            # otherwise raise an uncaught regex error straight from user
            # input.
            filtered = filtered[haystack.str.contains(s, na=False, regex=False)]

        st.caption(f"{len(filtered)} member(s)")
        display = filtered.copy()
        display["events_attended"] = display["events_attended"].str.replace(",", ", ")
        st.dataframe(
            display.rename(columns={"events_attended": "Events attended"})[[
                "name", "email", "member_type", "job_role", "company",
                "year_of_study", "degree", "is_alumnus", "is_ambassador", "Events attended",
            ]],
            width="stretch",
        )


@st.dialog("Confirm delete")
def _confirm_delete_attendance_dialog(attendance_id: int, label: str):
    st.write(f"You are about to delete this attendance record: **{label}**.")
    st.markdown("Are you sure you want to delete this record? **This cannot be undone.**")
    c1, c2 = st.columns(2)
    if c1.button("Cancel"):
        st.rerun()
    if c2.button("Confirm delete", type="primary"):
        conn = st.session_state["_conn"]
        conn.execute("DELETE FROM attendance WHERE attendance_id = ?", (attendance_id,))
        conn.commit()
        db.log_edit(conn, f"Attendance record deleted: {label}")
        st.session_state["_attendance_deleted_notice"] = label
        st.rerun()


def _attendance_records_section(conn):
    """Delete a single mistaken attendance record (wrong event/status
    logged) -- a hard delete, unlike the GDPR tab's anonymize-in-place:
    this is correcting a data-entry error, not fulfilling a privacy
    request, so there's no person's data to protect by keeping the row
    around unlinked. Logged to edit_log, separate from deletion_log."""
    st.session_state["_conn"] = conn

    if st.session_state.get("_attendance_deleted_notice"):
        st.success(f"Deleted attendance record: {st.session_state.pop('_attendance_deleted_notice')}")

    with st.expander("Attendance records (delete a mistaken entry)", expanded=False):
        records = db.df(
            conn,
            """SELECT a.attendance_id, e.name AS event_name, e.date AS event_date,
                      COALESCE(m.name, '(anonymized/removed)') AS member_name,
                      a.status, a.source_type
               FROM attendance a
               JOIN events e ON e.event_id = a.event_id
               LEFT JOIN members m ON m.member_id = a.member_id
               ORDER BY e.date DESC, a.attendance_id DESC""",
        )
        if records.empty:
            st.caption("No attendance records yet.")
            return

        st.dataframe(records.drop(columns=["attendance_id"]), width="stretch")

        delete_id = st.selectbox(
            "Select a record to delete",
            options=[None] + list(records["attendance_id"]),
            format_func=lambda aid: "-- select --" if aid is None else (
                f"{records.loc[records.attendance_id == aid, 'member_name'].iloc[0]} — "
                f"{records.loc[records.attendance_id == aid, 'event_name'].iloc[0]} — "
                f"{records.loc[records.attendance_id == aid, 'status'].iloc[0]}"
            ),
            key="attendance_delete_select",
        )
        if delete_id is not None:
            row = records.loc[records.attendance_id == delete_id].iloc[0]
            label = f"{row['member_name']} — {row['event_name']} — {row['status']}"
            if st.button("Delete record", type="primary", key="attendance_delete_btn"):
                _confirm_delete_attendance_dialog(int(delete_id), label)


def render(conn):
    st.header("Member attendance")
    _summary_charts(conn)
    st.divider()
    _members_list(conn)
    st.divider()
    _attendance_records_section(conn)
    st.divider()
    _import_section(conn)
    st.divider()
    _excel_import_section(conn)
    st.divider()
    _manual_form(conn)
