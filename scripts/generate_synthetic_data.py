"""Populate the dashboard's SQLite database with synthetic test data, write a
mock Luma-style CSV export for testing the import + column-mapping flow, and
run a sanity check of the GDPR anonymize/delete function.

Usage:
    python scripts/generate_synthetic_data.py
"""
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import db

random.seed(42)

SAMPLE_DATA_DIR = Path(__file__).resolve().parent.parent / "sample_data"

FIRST_NAMES = [
    "Ava", "Liam", "Maya", "Noah", "Priya", "Ethan", "Zoe", "Omar", "Grace", "Kai",
    "Sofia", "Lucas", "Nina", "Diego", "Ruth", "Sam", "Isla", "Theo", "Amara", "Ben",
    "Chloe", "Felix", "Hana", "Ivan", "Jade", "Kofi", "Lena", "Marco", "Nia", "Owen",
    "Petra", "Quinn", "Rosa", "Simon", "Tara", "Umar", "Vera", "Will", "Yara", "Zane",
]
LAST_NAMES = [
    "Patel", "Johnson", "Kim", "Garcia", "Chen", "Brown", "Diallo", "Novak", "Silva",
    "Nguyen", "Adeyemi", "Rossi", "Muller", "Sato", "Okafor", "Kowalski", "Haddad",
    "Larsen", "Costa", "Ibrahim",
]
COMPANIES = ["Acme Corp", "Globex", "Initech", "Umbrella Labs", "Hooli", "Northwind", "Vertex Systems"]
JOB_ROLES_NONSTUDENT = ["Software Engineer", "Product Manager", "Recruiter", "Designer", "Data Analyst", "Marketing Lead"]
YEARS_OF_STUDY = ["1st year", "2nd year", "3rd year", "4th year", "Masters", "PhD"]
DEGREES = ["Computer Science", "Mechanical Engineering", "Biochemistry", "Economics", "Mathematics", "Physics"]

AMBASSADOR_NAMES = [
    "Jordan Alvarez", "Casey Nakamura", "Riley Thompson", "Morgan Osei",
    "Taylor Bianchi", "Avery Lindqvist", "Dana Okoye", "Skyler Fontaine",
]


def make_email(name: str, domain: str) -> str:
    slug = name.lower().replace(" ", ".").replace("'", "")
    return f"{slug}@{domain}"


def reset_db(conn):
    has_sequence_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'"
    ).fetchone()
    # members.ambassador_id and ambassadors.member_id form a mutual FK pair,
    # so a full wipe needs FK checks off to avoid ordering issues.
    conn.execute("PRAGMA foreign_keys = OFF")
    for table in [
        "deletion_log", "ambassador_social_posts", "feedback", "attendance",
        "ambassadors", "members", "events",
    ]:
        conn.execute(f"DELETE FROM {table}")
        if has_sequence_table:
            conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")


def seed_events(conn):
    events = [
        ("Ambassador Training Workshop", "2026-01-20", "ambassador_workshop"),
        ("Spring Kickoff Mixer", "2026-02-10", "normal"),
        ("Campus Tech Talk", "2026-03-15", "normal"),
        ("Spring Networking Night", "2026-05-05", "normal"),
        ("Summer Leadership Workshop", "2026-07-10", "ambassador_workshop"),
    ]
    ids = {}
    for name, ev_date, ev_type in events:
        cur = conn.execute("INSERT INTO events (name, date, type) VALUES (?, ?, ?)", (name, ev_date, ev_type))
        ids[name] = cur.lastrowid
    conn.commit()
    return ids


def seed_members(conn, n=30):
    members = []
    used_names = set()
    for _ in range(n):
        while True:
            name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
            if name not in used_names:
                used_names.add(name)
                break
        email = make_email(name, "campus.edu" if random.random() < 0.6 else "example.com")
        member_type = "student" if random.random() < 0.6 else "non-student"
        if member_type == "student":
            job_role, company = None, None
            year_of_study = random.choice(YEARS_OF_STUDY)
            degree = random.choice(DEGREES)
            is_alumnus = False
        else:
            job_role = random.choice(JOB_ROLES_NONSTUDENT)
            company = random.choice(COMPANIES)
            year_of_study, degree = None, None
            is_alumnus = random.choice([True, True, False, False, None])
        cur = conn.execute(
            """INSERT INTO members (name, email, member_type, job_role, company, year_of_study,
               degree, is_alumnus, is_ambassador, ambassador_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)""",
            (
                name, email, member_type, job_role, company, year_of_study, degree,
                None if is_alumnus is None else int(is_alumnus),
            ),
        )
        members.append({"member_id": cur.lastrowid, "name": name, "email": email, "member_type": member_type})
    conn.commit()
    return members


def seed_ambassadors(conn, members):
    ambassadors = []
    linked_members = random.sample(members, k=7)
    for i, name in enumerate(AMBASSADOR_NAMES):
        linked = linked_members[i] if i < len(linked_members) else None
        email = linked["email"] if linked else make_email(name, "campus.edu")
        cur = conn.execute(
            "INSERT INTO ambassadors (member_id, name, email) VALUES (?, ?, ?)",
            (linked["member_id"] if linked else None, name, email),
        )
        ambassador_id = cur.lastrowid
        if linked:
            conn.execute(
                "UPDATE members SET is_ambassador=1, ambassador_id=? WHERE member_id=?",
                (ambassador_id, linked["member_id"]),
            )
        ambassadors.append({"ambassador_id": ambassador_id, "name": name, "email": email, "member_id": linked["member_id"] if linked else None})
    conn.commit()
    return ambassadors


def seed_attendance_and_feedback(conn, event_ids, members, ambassadors):
    low_rated_event = event_ids["Campus Tech Talk"]
    for event_name, event_id in event_ids.items():
        attendees = random.sample(members, k=random.randint(14, 22))
        for m in attendees:
            status = random.choices(["attended", "did not attend"], weights=[0.75, 0.25])[0]
            source_type = random.choices(
                ["student_ambassador", "social_media", "other"], weights=[0.4, 0.3, 0.3]
            )[0]
            referring_ambassador_id = None
            if source_type == "student_ambassador":
                referring_ambassador_id = random.choice(ambassadors)["ambassador_id"]
            conn.execute(
                """INSERT INTO attendance (member_id, event_id, status, source_type, referring_ambassador_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (m["member_id"], event_id, status, source_type, referring_ambassador_id),
            )
            if status == "attended" and random.random() < 0.6:
                if event_id == low_rated_event:
                    rating = random.choices([1, 2, 3, 4, 5], weights=[0.35, 0.35, 0.2, 0.07, 0.03])[0]
                else:
                    rating = random.choices([1, 2, 3, 4, 5], weights=[0.05, 0.1, 0.2, 0.3, 0.35])[0]
                comments = random.choice([
                    "Really enjoyed the speakers this time.",
                    "Venue was a bit cramped but content was solid.",
                    "Would love more networking time.",
                    "Great organization overall.",
                    "Not what I expected, could be better.",
                    "",
                    "The Q&A ran long but was valuable.",
                ])
                ev_date = conn.execute("SELECT date FROM events WHERE event_id=?", (event_id,)).fetchone()[0]
                submitted = (date.fromisoformat(ev_date) + timedelta(days=random.randint(1, 5))).isoformat()
                conn.execute(
                    "INSERT INTO feedback (member_id, event_id, rating, comments, submitted_date) VALUES (?, ?, ?, ?, ?)",
                    (m["member_id"], event_id, rating, comments or None, submitted),
                )

    # A couple of walk-ins with no matched member record, to demonstrate the
    # nullable member_id on attendance.
    any_event = next(iter(event_ids.values()))
    conn.execute(
        "INSERT INTO attendance (member_id, event_id, status, source_type, referring_ambassador_id) VALUES (NULL, ?, 'attended', 'other', NULL)",
        (any_event,),
    )
    conn.commit()


def seed_social_posts(conn, event_ids, ambassadors):
    events = list(event_ids.values())
    for amb in ambassadors:
        for _ in range(random.randint(2, 5)):
            event_id = random.choice(events)
            ev_date = conn.execute("SELECT date FROM events WHERE event_id=?", (event_id,)).fetchone()[0]
            posted = (date.fromisoformat(ev_date) - timedelta(days=random.randint(0, 10))).isoformat()
            conn.execute(
                "INSERT INTO ambassador_social_posts (ambassador_id, event_id, date_posted) VALUES (?, ?, ?)",
                (amb["ambassador_id"], event_id, posted),
            )
    conn.commit()


def write_mock_luma_csv(conn, event_ids, members, ambassadors):
    """CSV for the 'Summer Leadership Workshop' event: a mix of brand-new
    registrants and a couple of emails that already exist as members, to
    exercise both member creation and update/dedupe during import."""
    target_event = "Summer Leadership Workshop"
    existing_sample = random.sample(members, k=3)
    new_registrants = []
    for _ in range(10):
        name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
        new_registrants.append(name)

    rows = []
    # Intentionally varied raw text (including legacy-sounding values like
    # "Registered") to exercise the two-bucket status value-mapping UI.
    statuses = ["Attended", "Registered", "No Show", "Did Not Attend"]
    sources = ["Student Ambassador", "Instagram", "Twitter", "Friend told me", "Other"]
    amb_names = [a["name"] for a in ambassadors]

    for m in existing_sample:
        rows.append({
            "Full Name": m["name"],
            "Email": m["email"],
            "Status": random.choice(statuses),
            "How did you hear about us?": random.choice(sources),
            "Referred By": random.choice(amb_names) if random.random() < 0.5 else "",
            "Current Role": "",
            "Company/School": "",
            "Year of Study": "",
            "Degree": "",
            "Alumni Status": "",
            "Q: What are you hoping to learn at this event?": "Leadership skills",
            "Q: Dietary restrictions?": "",
        })

    for name in new_registrants:
        email = make_email(name, "newsignup.com")
        source = random.choice(sources)
        is_student = random.random() < 0.5
        rows.append({
            "Full Name": name,
            "Email": email,
            "Status": random.choice(statuses),
            "How did you hear about us?": source,
            "Referred By": random.choice(amb_names) if source == "Student Ambassador" else "",
            "Current Role": "" if is_student else random.choice(JOB_ROLES_NONSTUDENT),
            "Company/School": "" if is_student else random.choice(COMPANIES),
            "Year of Study": random.choice(YEARS_OF_STUDY) if is_student else "",
            "Degree": random.choice(DEGREES) if is_student else "",
            "Alumni Status": "" if is_student else random.choice(["Yes", "No", ""]),
            "Q: What are you hoping to learn at this event?": random.choice(
                ["Networking tips", "Public speaking", "Team management", ""]
            ),
            "Q: Dietary restrictions?": random.choice(["None", "Vegetarian", ""]),
        })

    df = pd.DataFrame(rows)
    SAMPLE_DATA_DIR.mkdir(exist_ok=True)
    out_path = SAMPLE_DATA_DIR / "mock_luma_export.csv"
    df.to_csv(out_path, index=False)
    print(f"Wrote mock Luma CSV for '{target_event}' -> {out_path} ({len(df)} rows)")


def run_anonymize_check(conn):
    print("\n--- GDPR anonymize/delete sanity check ---")

    def snapshot():
        return {
            "attendance_total": conn.execute("SELECT COUNT(*) FROM attendance").fetchone()[0],
            "feedback_total": conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0],
            "avg_rating": conn.execute("SELECT AVG(rating) FROM feedback").fetchone()[0],
            "members_total": conn.execute("SELECT COUNT(*) FROM members").fetchone()[0],
            "ambassadors_total": conn.execute("SELECT COUNT(*) FROM ambassadors").fetchone()[0],
            "posts_total": conn.execute("SELECT COUNT(*) FROM ambassador_social_posts").fetchone()[0],
        }

    # Case 1: plain (non-ambassador) member with attendance + feedback.
    candidate = conn.execute(
        """SELECT m.member_id, m.name FROM members m
           WHERE m.is_ambassador = 0
             AND EXISTS (SELECT 1 FROM feedback f WHERE f.member_id = m.member_id)
           LIMIT 1"""
    ).fetchone()
    assert candidate is not None, "expected at least one non-ambassador member with feedback"

    before = snapshot()
    per_event_before = dict(conn.execute("SELECT event_id, COUNT(*) FROM attendance GROUP BY event_id").fetchall())
    db.anonymize_member(conn, candidate["member_id"])
    after = snapshot()
    per_event_after = dict(conn.execute("SELECT event_id, COUNT(*) FROM attendance GROUP BY event_id").fetchall())

    assert after["attendance_total"] == before["attendance_total"], "attendance rows must not be deleted"
    assert after["feedback_total"] == before["feedback_total"], "feedback rows must not be deleted"
    assert abs((after["avg_rating"] or 0) - (before["avg_rating"] or 0)) < 1e-9, "avg rating must be unchanged"
    assert per_event_before == per_event_after, "per-event attendance counts must be unchanged"
    assert after["members_total"] == before["members_total"] - 1, "member row should be removed"
    remaining = conn.execute("SELECT COUNT(*) FROM members WHERE member_id=?", (candidate["member_id"],)).fetchone()[0]
    assert remaining == 0
    orphaned_attendance = conn.execute(
        "SELECT COUNT(*) FROM attendance WHERE member_id IS NULL"
    ).fetchone()[0]
    assert orphaned_attendance >= 1
    print(f"PASS: anonymized non-ambassador member '{candidate['name']}' -- attendance/feedback totals and per-event counts unchanged.")

    # Case 2: ambassador member with referrals + social posts.
    amb_candidate = conn.execute(
        """SELECT m.member_id, m.name, m.ambassador_id FROM members m
           WHERE m.is_ambassador = 1
             AND EXISTS (SELECT 1 FROM ambassador_social_posts p WHERE p.ambassador_id = m.ambassador_id)
           LIMIT 1"""
    ).fetchone()
    assert amb_candidate is not None, "expected at least one ambassador with a logged post"

    before2 = snapshot()
    ambassador_id = amb_candidate["ambassador_id"]
    referral_count_before = conn.execute(
        "SELECT COUNT(*) FROM attendance WHERE referring_ambassador_id=?", (ambassador_id,)
    ).fetchone()[0]
    db.anonymize_member(conn, amb_candidate["member_id"])
    after2 = snapshot()

    assert after2["attendance_total"] == before2["attendance_total"], "attendance rows must not be deleted"
    assert after2["feedback_total"] == before2["feedback_total"], "feedback rows must not be deleted"
    assert after2["posts_total"] == before2["posts_total"], "social post rows must not be deleted"
    assert after2["ambassadors_total"] == before2["ambassadors_total"] - 1, "ambassador row should be removed"
    dangling_referrals = conn.execute(
        "SELECT COUNT(*) FROM attendance WHERE referring_ambassador_id=?", (ambassador_id,)
    ).fetchone()[0]
    assert dangling_referrals == 0, "no attendance row should still point at the deleted ambassador"
    unlinked_posts = conn.execute(
        "SELECT COUNT(*) FROM ambassador_social_posts WHERE ambassador_id IS NULL"
    ).fetchone()[0]
    assert unlinked_posts >= 1
    print(
        f"PASS: anonymized ambassador '{amb_candidate['name']}' -- {referral_count_before} referral row(s) "
        "and their social posts unlinked, ambassador row removed, attendance/feedback/post totals unchanged."
    )

    log_rows = conn.execute("SELECT action_description FROM deletion_log").fetchall()
    assert len(log_rows) == 2
    for r in log_rows:
        assert "@" not in r["action_description"], "deletion log must not contain personal data"
    print("PASS: deletion_log has 2 entries with no personal data.")


def main():
    db.init_db()
    conn = db.get_connection()
    reset_db(conn)

    event_ids = seed_events(conn)
    members = seed_members(conn)
    ambassadors = seed_ambassadors(conn, members)
    seed_attendance_and_feedback(conn, event_ids, members, ambassadors)
    seed_social_posts(conn, event_ids, ambassadors)
    write_mock_luma_csv(conn, event_ids, members, ambassadors)

    print(f"\nSeeded {len(event_ids)} events, {len(members)} members, {len(ambassadors)} ambassadors.")
    run_anonymize_check(conn)
    print("\nDone. Run `streamlit run app.py` to explore the dashboard.")
    conn.close()


if __name__ == "__main__":
    main()
