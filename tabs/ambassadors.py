import datetime as dt
import html

import streamlit as st

import db
from scoring import compute_ambassador_leaderboard

# Podium visuals reuse the theme's CSS custom properties (defined at :root
# in style.py) so they follow the light/dark toggle with no extra work.
_PODIUM_SPECS = [
    {"rank": 1, "height": 170, "opacity": 1.0, "medal": "\U0001F947", "medal_size": "2rem", "name_size": "1.05rem"},
    {"rank": 2, "height": 125, "opacity": 0.85, "medal": "\U0001F948", "medal_size": "1.5rem", "name_size": "0.95rem"},
    {"rank": 3, "height": 95, "opacity": 0.7, "medal": "\U0001F949", "medal_size": "1.5rem", "name_size": "0.95rem"},
]


def _podium_block(spec, name, score):
    # Built as one unbroken line (no newlines/indentation): st.markdown runs
    # content through a CommonMark parser first, and a line indented 4+
    # spaces reads as an indented code block -- which silently breaks raw
    # HTML rendering for everything after the first such line.
    safe_name = html.escape(str(name))
    return (
        f'<div style="flex:1; max-width:190px; text-align:center;">'
        f'<div style="font-size:{spec["medal_size"]};">{spec["medal"]}</div>'
        f'<div style="font-family:\'Playfair Display\', Georgia, serif; font-weight:700; '
        f'font-size:{spec["name_size"]}; color:var(--text); overflow-wrap:break-word;">{safe_name}</div>'
        f'<div style="color:var(--text-muted); font-size:0.85rem; margin-bottom:0.5rem;">Score: {score}</div>'
        f'<div style="height:{spec["height"]}px; border-radius:12px 12px 0 0; background:var(--gradient); '
        f'opacity:{spec["opacity"]}; display:flex; align-items:flex-start; justify-content:center; padding-top:0.6rem;">'
        f'<span style="color:#fff; font-weight:800; font-size:1.4rem; '
        f'text-shadow:0 1px 2px rgba(0,0,0,0.25);">{spec["rank"]}</span>'
        f'</div>'
        f'</div>'
    )


def _render_podium(rows):
    """rows: up to 3 dicts (name/score), ranked 1st..3rd. Lays out
    2nd-1st-3rd so 1st stays centered; degrades gracefully below 3."""
    if not rows:
        return
    ranked = {i + 1: r for i, r in enumerate(rows)}
    if len(ranked) >= 3:
        order = [2, 1, 3]
    elif len(ranked) == 2:
        order = [2, 1]
    else:
        order = [1]
    blocks = "".join(
        _podium_block(_PODIUM_SPECS[rank - 1], ranked[rank]["name"], ranked[rank]["score"])
        for rank in order
    )
    st.markdown(
        f'<div style="display:flex; align-items:flex-end; justify-content:center; '
        f'gap:1.25rem; margin:1rem 0 1.5rem; flex-wrap:wrap;">{blocks}</div>',
        unsafe_allow_html=True,
    )


def _roster(conn):
    st.subheader("Ambassador roster")
    ambassadors = db.get_ambassadors_df(conn)

    with st.form("add_ambassador_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        name = c1.text_input("Name")
        email = c2.text_input("Email")
        if st.form_submit_button("Add ambassador"):
            if not name or not email:
                st.error("Name and email are required.")
            elif db.find_ambassador_by_email(conn, email):
                st.error("An ambassador with that email already exists.")
            else:
                member = db.find_member_by_email(conn, email)
                cur = conn.execute(
                    "INSERT INTO ambassadors (member_id, name, email) VALUES (?, ?, ?)",
                    (member["member_id"] if member else None, name, email),
                )
                ambassador_id = cur.lastrowid
                if member:
                    conn.execute(
                        "UPDATE members SET is_ambassador=1, ambassador_id=? WHERE member_id=?",
                        (ambassador_id, member["member_id"]),
                    )
                conn.commit()
                st.success(f"Added ambassador '{name}'.")
                st.rerun()

    if ambassadors.empty:
        st.caption("No ambassadors yet.")
        return

    st.dataframe(ambassadors[["name", "email"]], width="stretch")

    remove_id = st.selectbox(
        "Remove an ambassador",
        options=[None] + list(ambassadors["ambassador_id"]),
        format_func=lambda aid: "-- select --" if aid is None else ambassadors.loc[ambassadors.ambassador_id == aid, "name"].iloc[0],
    )
    if remove_id is not None:
        referrals = conn.execute(
            "SELECT COUNT(*) FROM attendance WHERE referring_ambassador_id=?", (remove_id,)
        ).fetchone()[0]
        posts = conn.execute(
            "SELECT COUNT(*) FROM ambassador_social_posts WHERE ambassador_id=?", (remove_id,)
        ).fetchone()[0]
        st.warning(
            f"Removing this ambassador will detach attribution from {referrals} referral(s) "
            f"and {posts} social post(s) (the historical records stay, just unattributed)."
        )
        if st.button("Confirm remove", type="primary"):
            conn.execute("UPDATE attendance SET referring_ambassador_id=NULL WHERE referring_ambassador_id=?", (remove_id,))
            conn.execute("UPDATE ambassador_social_posts SET ambassador_id=NULL WHERE ambassador_id=?", (remove_id,))
            conn.execute("UPDATE members SET is_ambassador=0, ambassador_id=NULL WHERE ambassador_id=?", (remove_id,))
            conn.execute("DELETE FROM ambassadors WHERE ambassador_id=?", (remove_id,))
            conn.commit()
            st.success("Ambassador removed.")
            st.rerun()


def _leaderboard(conn):
    st.subheader("Leaderboard")
    board = compute_ambassador_leaderboard(conn)
    if board.empty:
        st.caption("No ambassadors yet.")
        return

    top5 = board.head(5).to_dict("records")
    _render_podium(top5[:3])
    for i, r in enumerate(top5[3:5], start=4):
        st.markdown(f"**{i}.** {r['name']} — {r['score']}")

    with st.expander("View full leaderboard"):
        st.dataframe(
            board.rename(columns={
                "successful_referrals": "Referrals (attended)",
                "social_posts_count": "Social posts",
                "own_events_attended_count": "Own events attended",
                "score": "Score",
            })[["name", "email", "Referrals (attended)", "Social posts", "Own events attended", "Score"]],
            width="stretch",
        )

    st.markdown("**Drill-down**")
    amb_id = st.selectbox(
        "Ambassador", options=board["ambassador_id"],
        format_func=lambda aid: board.loc[board.ambassador_id == aid, "name"].iloc[0],
        key="drilldown_amb",
    )
    row = board[board.ambassador_id == amb_id].iloc[0]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Score", row["score"])
    m2.metric("Referrals", int(row["successful_referrals"]))
    m3.metric("Social posts", int(row["social_posts_count"]))
    m4.metric("Own events attended", int(row["own_events_attended_count"]))

    referred = db.df(
        conn,
        """SELECT m.name, m.email, a.status, e.name AS event_name
           FROM attendance a JOIN events e ON e.event_id = a.event_id
           LEFT JOIN members m ON m.member_id = a.member_id
           WHERE a.referring_ambassador_id = ?""",
        (int(amb_id),),
    )
    st.caption("Referred attendees")
    st.dataframe(referred, width="stretch")

    posts = db.df(
        conn,
        """SELECT p.date_posted, e.name AS event_name
           FROM ambassador_social_posts p JOIN events e ON e.event_id = p.event_id
           WHERE p.ambassador_id = ? ORDER BY p.date_posted DESC""",
        (int(amb_id),),
    )
    st.caption("Social posts")
    st.dataframe(posts, width="stretch")


def _log_post(conn):
    st.subheader("Log a social media post")
    ambassadors = db.get_ambassadors_df(conn)
    events = db.get_events_df(conn)
    if ambassadors.empty or events.empty:
        st.caption("Add an ambassador and an event first.")
        return
    with st.form("log_post_form", clear_on_submit=True):
        amb_id = st.selectbox(
            "Ambassador", options=ambassadors["ambassador_id"],
            format_func=lambda aid: ambassadors.loc[ambassadors.ambassador_id == aid, "name"].iloc[0],
        )
        event_id = st.selectbox(
            "Event", options=events["event_id"],
            format_func=lambda eid: events.loc[events.event_id == eid, "name"].iloc[0],
        )
        date_posted = st.date_input("Date posted", value=dt.date.today())
        if st.form_submit_button("Log post"):
            conn.execute(
                "INSERT INTO ambassador_social_posts (ambassador_id, event_id, date_posted) VALUES (?, ?, ?)",
                (int(amb_id), int(event_id), str(date_posted)),
            )
            conn.commit()
            st.success("Post logged.")
            st.rerun()


def render(conn):
    st.header("Ambassador performance")
    _leaderboard(conn)
    st.divider()
    _roster(conn)
    st.divider()
    _log_post(conn)
