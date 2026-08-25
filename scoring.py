"""Ambassador composite-score calculation.

score = (successful_referrals x 3)
      + (social_posts_count x 1)
      + (own_events_attended_count x 1)

- successful_referrals: attendance rows this ambassador referred where the
  referred person actually attended (status == 'attended').
- social_posts_count: rows in ambassador_social_posts for this ambassador.
- own_events_attended_count: events (normal or workshop) this ambassador
  personally attended, via their own member record.
"""
import pandas as pd


def compute_ambassador_leaderboard(conn) -> pd.DataFrame:
    ambassadors = pd.read_sql_query("SELECT * FROM ambassadors", conn)
    attendance = pd.read_sql_query("SELECT * FROM attendance", conn)
    posts = pd.read_sql_query("SELECT * FROM ambassador_social_posts", conn)

    if ambassadors.empty:
        return pd.DataFrame(
            columns=[
                "ambassador_id", "name", "email", "successful_referrals",
                "social_posts_count", "own_events_attended_count", "score",
            ]
        )

    attended = attendance[attendance["status"] == "attended"]

    referrals = (
        attended[attended["referring_ambassador_id"].notna()]
        .groupby("referring_ambassador_id")
        .size()
    )

    posts_count = posts.dropna(subset=["ambassador_id"]).groupby("ambassador_id").size()

    own_member_ids = ambassadors.set_index("member_id")["ambassador_id"].dropna() if "member_id" in ambassadors else pd.Series(dtype=int)
    attended_by_member = attended.groupby("member_id").size()
    # map each ambassador's own member_id -> their attended-event count
    own_events = pd.Series(dtype=int)
    if not ambassadors.empty:
        tmp = ambassadors[["ambassador_id", "member_id"]].dropna(subset=["member_id"]).copy()
        tmp["own_count"] = tmp["member_id"].map(attended_by_member).fillna(0)
        own_events = tmp.set_index("ambassador_id")["own_count"]

    board = ambassadors[["ambassador_id", "name", "email"]].copy()
    board["successful_referrals"] = board["ambassador_id"].map(referrals).fillna(0).astype(int)
    board["social_posts_count"] = board["ambassador_id"].map(posts_count).fillna(0).astype(int)
    board["own_events_attended_count"] = board["ambassador_id"].map(own_events).fillna(0).astype(int)

    board["score"] = (
        board["successful_referrals"] * 3
        + board["social_posts_count"] * 1
        + board["own_events_attended_count"] * 1
    ).round(2)

    return board.sort_values("score", ascending=False).reset_index(drop=True)
