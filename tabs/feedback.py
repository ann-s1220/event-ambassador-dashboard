import pandas as pd
import streamlit as st

import db

LOW_RATING_THRESHOLD = 3.0


@st.dialog("Confirm delete")
def _confirm_delete_feedback_dialog(feedback_id: int, label: str):
    st.write(f"You are about to delete this feedback entry: **{label}**.")
    st.markdown("Are you sure you want to delete this entry? **This cannot be undone.**")
    c1, c2 = st.columns(2)
    if c1.button("Cancel"):
        st.rerun()
    if c2.button("Confirm delete", type="primary"):
        conn = st.session_state["_conn"]
        conn.execute("DELETE FROM feedback WHERE feedback_id = ?", (feedback_id,))
        conn.commit()
        db.log_edit(conn, f"Feedback entry deleted: {label}")
        st.session_state["_feedback_deleted_notice"] = label
        st.rerun()


def _feedback_records_section(conn):
    """Delete a single mistaken feedback entry (duplicate or test
    submission) -- a hard delete, unlike the GDPR tab's anonymize-in-place:
    this is correcting a data-entry error, not fulfilling a privacy
    request. Kept anonymous (no member name/email) like the rest of this
    tab -- identifying a duplicate/test entry only needs the event,
    rating, and comment, not who submitted it. Logged to edit_log,
    separate from deletion_log."""
    st.session_state["_conn"] = conn

    if st.session_state.get("_feedback_deleted_notice"):
        st.success(f"Deleted feedback entry: {st.session_state.pop('_feedback_deleted_notice')}")

    with st.expander("Feedback entries (delete a mistaken entry)", expanded=False):
        records = db.df(
            conn,
            """SELECT f.feedback_id, e.name AS event_name, f.rating, f.comments, f.submitted_date
               FROM feedback f JOIN events e ON e.event_id = f.event_id
               ORDER BY f.submitted_date DESC, f.feedback_id DESC""",
        )
        if records.empty:
            st.caption("No feedback entries yet.")
            return

        st.dataframe(records.drop(columns=["feedback_id"]), width="stretch")

        delete_id = st.selectbox(
            "Select an entry to delete",
            options=[None] + list(records["feedback_id"]),
            format_func=lambda fid: "-- select --" if fid is None else (
                f"{records.loc[records.feedback_id == fid, 'event_name'].iloc[0]} — "
                f"rating {records.loc[records.feedback_id == fid, 'rating'].iloc[0]} — "
                f"{records.loc[records.feedback_id == fid, 'submitted_date'].iloc[0]}"
            ),
            key="feedback_delete_select",
        )
        if delete_id is not None:
            row = records.loc[records.feedback_id == delete_id].iloc[0]
            label = f"{row['event_name']} — rating {row['rating']} — {row['submitted_date']}"
            if st.button("Delete entry", type="primary", key="feedback_delete_btn"):
                _confirm_delete_feedback_dialog(int(delete_id), label)


def render(conn):
    st.header("Member feedback")
    st.caption(
        "Displayed anonymously: no names or member IDs are shown here, even though "
        "member_id is retained in the database for internal aggregation."
    )

    feedback = db.df(
        conn,
        """SELECT f.event_id, e.name AS event_name, f.rating, f.comments, f.submitted_date
           FROM feedback f JOIN events e ON e.event_id = f.event_id""",
    )

    if feedback.empty:
        st.info("No feedback submitted yet.")
        return

    st.subheader("Overview")
    c1, c2 = st.columns(2)
    c1.metric("Average rating", round(feedback["rating"].mean(), 2))
    c2.metric("Responses", len(feedback))

    trend_df = feedback.copy()
    trend_df["month"] = pd.to_datetime(trend_df["submitted_date"]).dt.to_period("M").astype(str)
    trend = trend_df.groupby("month")["rating"].mean().sort_index()
    st.markdown("**Trend over time (avg rating by month)**")
    st.line_chart(trend)

    st.subheader("Per-event breakdown")
    per_event = feedback.groupby(["event_id", "event_name"]).agg(
        avg_rating=("rating", "mean"), responses=("rating", "size")
    ).reset_index().sort_values("event_name")
    per_event["avg_rating"] = per_event["avg_rating"].round(2)
    st.dataframe(per_event[["event_name", "avg_rating", "responses"]], width="stretch")

    event_choice = st.selectbox(
        "View comments for event", options=per_event["event_id"],
        format_func=lambda eid: per_event.loc[per_event.event_id == eid, "event_name"].iloc[0],
    )
    comments = feedback[(feedback.event_id == event_choice) & feedback["comments"].notna() & (feedback["comments"] != "")]
    if comments.empty:
        st.caption("No comments for this event.")
    else:
        st.caption("Comments are free text and may occasionally contain self-identifying details.")
        for _, r in comments.sort_values("submitted_date", ascending=False).iterrows():
            st.markdown(f"- **{r['rating']}/5** -- {r['comments']}")

    st.subheader("Low-rated events / periods")
    flagged_events = per_event[per_event["avg_rating"] < LOW_RATING_THRESHOLD]
    if flagged_events.empty:
        st.success(f"No events below the {LOW_RATING_THRESHOLD} rating threshold.")
    else:
        for _, r in flagged_events.iterrows():
            st.error(f"{r['event_name']}: avg rating {r['avg_rating']} ({r['responses']} responses)")

    flagged_months = trend[trend < LOW_RATING_THRESHOLD]
    if not flagged_months.empty:
        st.warning("Low-rated month(s): " + ", ".join(f"{m} ({v:.2f})" for m, v in flagged_months.items()))

    st.divider()
    _feedback_records_section(conn)
