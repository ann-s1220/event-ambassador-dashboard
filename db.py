"""SQLite schema and data-access helpers for the Event & Ambassador Dashboard.

GDPR note: personal data (name, email, job_role, company, comments) lives only
in `members` / `feedback`. `attendance`, `feedback`, and `ambassador_social_posts`
keep nullable member/ambassador foreign keys so a person can be anonymized by
nulling the pointer and deleting their identity row, while historical
aggregate records (counts, ratings) remain intact. See `anonymize_member`.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

DB_DIR = Path(__file__).parent / "data"
# demo branch only: a distinct filename from main's event_ambassador.db,
# so this branch can never open, seed into, or overwrite whatever real
# database a main checkout in the same working copy is using.
DB_PATH = DB_DIR / "demo_event_ambassador.db"

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    date TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('normal', 'ambassador_workshop'))
);

CREATE TABLE IF NOT EXISTS members (
    member_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    member_type TEXT NOT NULL CHECK (member_type IN ('student', 'non-student')) DEFAULT 'non-student',
    job_role TEXT,
    company TEXT,
    year_of_study TEXT,
    degree TEXT,
    is_alumnus INTEGER,
    is_ambassador INTEGER NOT NULL DEFAULT 0,
    ambassador_id INTEGER,
    FOREIGN KEY (ambassador_id) REFERENCES ambassadors(ambassador_id)
);

CREATE TABLE IF NOT EXISTS ambassadors (
    ambassador_id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    FOREIGN KEY (member_id) REFERENCES members(member_id)
);

CREATE TABLE IF NOT EXISTS attendance (
    attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER,
    event_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('attended','did not attend')),
    source_type TEXT NOT NULL CHECK (source_type IN ('social_media','student_ambassador','other')),
    referring_ambassador_id INTEGER,
    FOREIGN KEY (member_id) REFERENCES members(member_id),
    FOREIGN KEY (event_id) REFERENCES events(event_id),
    FOREIGN KEY (referring_ambassador_id) REFERENCES ambassadors(ambassador_id)
);

CREATE TABLE IF NOT EXISTS feedback (
    feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER,
    event_id INTEGER NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comments TEXT,
    submitted_date TEXT NOT NULL,
    FOREIGN KEY (member_id) REFERENCES members(member_id),
    FOREIGN KEY (event_id) REFERENCES events(event_id)
);

CREATE TABLE IF NOT EXISTS ambassador_social_posts (
    post_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ambassador_id INTEGER,
    event_id INTEGER NOT NULL,
    date_posted TEXT NOT NULL,
    FOREIGN KEY (ambassador_id) REFERENCES ambassadors(ambassador_id),
    FOREIGN KEY (event_id) REFERENCES events(event_id)
);

CREATE TABLE IF NOT EXISTS deletion_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    action_description TEXT NOT NULL
);

-- Separate from deletion_log on purpose: deletion_log is a GDPR erasure
-- trail and deliberately holds no identifying detail (see anonymize_member).
-- edit_log is plain internal auditing for hard deletes of data-entry
-- mistakes (a wrong attendance/feedback/social-post row) -- not privacy
-- requests -- so it can name what was deleted (event, status, rating, ...)
-- without mixing that into the GDPR-sensitive log.
CREATE TABLE IF NOT EXISTS edit_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    action_description TEXT NOT NULL
);
"""


def get_connection() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _migrate(conn)
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns/constraints introduced after a database may already have
    been created, so existing local .db files keep working without a reset."""
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(members)")}
    for col in ("year_of_study", "degree"):
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE members ADD COLUMN {col} TEXT")
    conn.commit()
    _migrate_attendance_status(conn)


def _migrate_attendance_status(conn: sqlite3.Connection) -> None:
    """Collapse the old three-state attendance.status ('registered',
    'attended', 'no-show') down to two ('attended', 'did not attend').
    SQLite can't alter a CHECK constraint in place, so this rebuilds the
    table. No-op once already migrated (or on a fresh database, since the
    table is already created with the new constraint by SCHEMA)."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='attendance'"
    ).fetchone()
    if row is None or "registered" not in row["sql"]:
        return

    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("ALTER TABLE attendance RENAME TO attendance_old")
    conn.execute("""
        CREATE TABLE attendance (
            attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER,
            event_id INTEGER NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('attended','did not attend')),
            source_type TEXT NOT NULL CHECK (source_type IN ('social_media','student_ambassador','other')),
            referring_ambassador_id INTEGER,
            FOREIGN KEY (member_id) REFERENCES members(member_id),
            FOREIGN KEY (event_id) REFERENCES events(event_id),
            FOREIGN KEY (referring_ambassador_id) REFERENCES ambassadors(ambassador_id)
        )
    """)
    conn.execute("""
        INSERT INTO attendance (attendance_id, member_id, event_id, status, source_type, referring_ambassador_id)
        SELECT attendance_id, member_id, event_id,
               CASE WHEN status = 'attended' THEN 'attended' ELSE 'did not attend' END,
               source_type, referring_ambassador_id
        FROM attendance_old
    """)
    conn.execute("DROP TABLE attendance_old")
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")


def infer_member_type(job_role, year_of_study, degree) -> str | None:
    """Best-effort member_type from whichever type-specific fields are
    present. Returns None when there isn't enough signal to decide."""
    if year_of_study or degree:
        return "student"
    if job_role:
        return "student" if "student" in job_role.lower() else "non-student"
    return None


def type_specific_fields(member_type, job_role, company, year_of_study, degree, is_alumnus):
    """Null out the fields that don't apply to member_type. Students can
    never be alumni, so is_alumnus is forced to False for them -- this also
    covers the non-student -> student conversion case, since it always
    runs whenever the resolved type is 'student'."""
    if member_type == "student":
        return None, None, year_of_study, degree, False
    return job_role, company, None, None, is_alumnus


def df(conn: sqlite3.Connection, query: str, params: tuple = ()) -> pd.DataFrame:
    return pd.read_sql_query(query, conn, params=params)


def get_events_df(conn) -> pd.DataFrame:
    return df(conn, "SELECT * FROM events ORDER BY date")


def get_members_df(conn) -> pd.DataFrame:
    return df(conn, "SELECT * FROM members ORDER BY name")


def get_ambassadors_df(conn) -> pd.DataFrame:
    return df(conn, "SELECT * FROM ambassadors ORDER BY name")


def get_attendance_df(conn) -> pd.DataFrame:
    return df(conn, "SELECT * FROM attendance")


def get_feedback_df(conn) -> pd.DataFrame:
    return df(conn, "SELECT * FROM feedback")


def get_posts_df(conn) -> pd.DataFrame:
    return df(conn, "SELECT * FROM ambassador_social_posts")


def get_deletion_log_df(conn) -> pd.DataFrame:
    return df(conn, "SELECT * FROM deletion_log ORDER BY log_id DESC")


def find_member_by_email(conn, email: str):
    row = conn.execute(
        "SELECT * FROM members WHERE lower(email) = lower(?)", (email.strip(),)
    ).fetchone()
    return row


def find_ambassador_by_email(conn, email: str):
    row = conn.execute(
        "SELECT * FROM ambassadors WHERE lower(email) = lower(?)", (email.strip(),)
    ).fetchone()
    return row


def find_ambassador_by_name(conn, name: str):
    row = conn.execute(
        "SELECT * FROM ambassadors WHERE lower(name) = lower(?)", (name.strip(),)
    ).fetchone()
    return row


def log_deletion(conn, action_description: str) -> None:
    conn.execute(
        "INSERT INTO deletion_log (timestamp, action_description) VALUES (?, ?)",
        (datetime.now(timezone.utc).isoformat(timespec="seconds"), action_description),
    )
    conn.commit()


def log_edit(conn, action_description: str) -> None:
    conn.execute(
        "INSERT INTO edit_log (timestamp, action_description) VALUES (?, ?)",
        (datetime.now(timezone.utc).isoformat(timespec="seconds"), action_description),
    )
    conn.commit()


def get_edit_log_df(conn) -> pd.DataFrame:
    return df(conn, "SELECT * FROM edit_log ORDER BY log_id DESC")


def get_anonymization_preview(conn, member_id: int) -> dict:
    """Counts of records that would be affected by anonymizing this member."""
    member = conn.execute("SELECT * FROM members WHERE member_id = ?", (member_id,)).fetchone()
    if member is None:
        raise ValueError(f"No member with id {member_id}")

    attendance_count = conn.execute(
        "SELECT COUNT(*) FROM attendance WHERE member_id = ?", (member_id,)
    ).fetchone()[0]
    feedback_count = conn.execute(
        "SELECT COUNT(*) FROM feedback WHERE member_id = ?", (member_id,)
    ).fetchone()[0]

    ambassador_id = member["ambassador_id"]
    referrals_count = 0
    posts_count = 0
    if ambassador_id is not None:
        referrals_count = conn.execute(
            "SELECT COUNT(*) FROM attendance WHERE referring_ambassador_id = ?", (ambassador_id,)
        ).fetchone()[0]
        posts_count = conn.execute(
            "SELECT COUNT(*) FROM ambassador_social_posts WHERE ambassador_id = ?", (ambassador_id,)
        ).fetchone()[0]

    return {
        "member_id": member_id,
        "name": member["name"],
        "email": member["email"],
        "is_ambassador": bool(member["is_ambassador"]),
        "attendance_rows_to_unlink": attendance_count,
        "feedback_rows_to_unlink": feedback_count,
        "referral_rows_to_unlink": referrals_count,
        "social_post_rows_to_unlink": posts_count,
        "ambassador_row_deleted": ambassador_id is not None,
    }


def anonymize_member(conn, member_id: int) -> dict:
    """GDPR erasure: unlink the member from all activity records (set FK to
    NULL) rather than deleting the activity rows themselves, then delete the
    member's (and, if applicable, ambassador's) identity row. Aggregate
    stats keyed on event_id / status / rating are unaffected since those
    rows still exist -- only the person-identifying pointer is removed.
    """
    preview = get_anonymization_preview(conn, member_id)
    ambassador_id = None
    member = conn.execute("SELECT ambassador_id FROM members WHERE member_id = ?", (member_id,)).fetchone()
    if member is not None:
        ambassador_id = member["ambassador_id"]

    conn.execute("UPDATE attendance SET member_id = NULL WHERE member_id = ?", (member_id,))
    conn.execute("UPDATE feedback SET member_id = NULL WHERE member_id = ?", (member_id,))

    if ambassador_id is not None:
        conn.execute(
            "UPDATE attendance SET referring_ambassador_id = NULL WHERE referring_ambassador_id = ?",
            (ambassador_id,),
        )
        conn.execute(
            "UPDATE ambassador_social_posts SET ambassador_id = NULL WHERE ambassador_id = ?",
            (ambassador_id,),
        )
        # members.ambassador_id <-> ambassadors.member_id is a mutual FK pair;
        # break both links before deleting either row to avoid a constraint error.
        conn.execute("UPDATE ambassadors SET member_id = NULL WHERE ambassador_id = ?", (ambassador_id,))
        conn.execute("UPDATE members SET ambassador_id = NULL WHERE member_id = ?", (member_id,))
        conn.execute("DELETE FROM ambassadors WHERE ambassador_id = ?", (ambassador_id,))

    conn.execute("DELETE FROM members WHERE member_id = ?", (member_id,))
    conn.commit()

    log_deletion(conn, "Member record anonymized and erased at their request")
    return preview
