import altair as alt
import pandas as pd
import streamlit as st

import db
from csv_import import (
    NONE_CHOICE, SOURCE_VALUES, STATUS_VALUES, TARGET_FIELDS,
    import_attendance_csv, preview_members, suggest_column_map, suggest_source_map,
    suggest_status_map, unique_values,
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
    arc = base.mark_arc(outerRadius=90)
    labels = base.mark_text(radius=112, size=13).encode(text="label:N")
    return (
        (arc + labels)
        .properties(title=title, width=280, height=280, padding={"left": 20, "right": 20, "top": 10, "bottom": 10})
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
    arc = base.mark_arc(outerRadius=90)
    labels = base.mark_text(radius=112, size=13).encode(text="label:N")
    return (
        (arc + labels)
        .properties(title=title, width=280, height=280, padding={"left": 20, "right": 20, "top": 10, "bottom": 10})
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

    data = pd.read_csv(uploaded)
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


def _manual_form(conn):
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

    with st.expander("Add a new event"):
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


def _summary_charts(conn):
    """Total attendance rate + source breakdown, side by side (Streamlit
    stacks columns automatically on narrow viewports). This is the first
    thing shown in the tab."""
    events = db.get_events_df(conn)
    attendance = db.get_attendance_df(conn)

    if events.empty:
        st.info("No events yet -- add one further down to start tracking attendance.")
        return

    event_choice = st.selectbox(
        "Event", options=["All"] + list(events["event_id"]),
        format_func=lambda eid: "All events" if eid == "All" else events.loc[events.event_id == eid, "name"].iloc[0],
        key="view_event",
    )
    att = attendance if event_choice == "All" else attendance[attendance.event_id == event_choice]
    scope_label = "all events" if event_choice == "All" else events.loc[events.event_id == event_choice, "name"].iloc[0]

    if att.empty:
        st.caption("No attendance records yet.")
        return

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Overall attendance rate** ({scope_label})")
        st.altair_chart(_attendance_pie_chart(att, scope_label), use_container_width=False)
        st.markdown(_attendance_stat_line(att))
    with col2:
        st.markdown(f"**Source breakdown** ({scope_label})")
        st.altair_chart(_source_pie_chart(att, scope_label), use_container_width=False)
        st.markdown(_source_stat_line(att))


def _members_list(conn):
    members = db.get_members_df(conn)
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
        fcol1, fcol2, fcol3 = st.columns(3)
        with fcol1:
            type_filter = st.multiselect(
                "Member type", ["student", "non-student"], default=["student", "non-student"],
                key="members_type_filter",
            )
        with fcol2:
            alum_filter = st.selectbox("Alumnus", ["All", "Yes", "No", "Unknown"], key="members_alum_filter")
        with fcol3:
            search = st.text_input("Search name, email, or event attended", key="members_search")

        filtered = members[members["member_type"].isin(type_filter)] if type_filter else members
        if alum_filter == "Yes":
            filtered = filtered[filtered["is_alumnus"] == 1]
        elif alum_filter == "No":
            filtered = filtered[filtered["is_alumnus"] == 0]
        elif alum_filter == "Unknown":
            filtered = filtered[filtered["is_alumnus"].isna()]
        if search:
            s = search.lower()
            filtered = filtered[
                filtered["name"].str.lower().str.contains(s, na=False)
                | filtered["email"].str.lower().str.contains(s, na=False)
                | filtered["events_attended"].str.lower().str.contains(s, na=False)
            ]

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


def render(conn):
    st.header("Member attendance")
    _summary_charts(conn)
    st.divider()
    _members_list(conn)
    st.divider()
    _import_section(conn)
    st.divider()
    _manual_form(conn)
