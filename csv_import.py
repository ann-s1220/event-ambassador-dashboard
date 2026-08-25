"""Luma-style CSV import: column mapping, value normalization, and the
create/update logic for members + attendance records."""
import pandas as pd

import db

TARGET_FIELDS = [
    "name", "email", "status", "source_type",
    "referring_ambassador_name", "job_role", "company",
    "year_of_study", "degree", "is_alumnus",
]

REQUIRED_FIELDS = {"name", "email"}

NONE_CHOICE = "-- none --"

STATUS_VALUES = ["attended", "did not attend"]
SOURCE_VALUES = ["social_media", "student_ambassador", "other"]

_AUTO_SUGGEST = {
    "name": ["full name", "name", "guest name", "attendee"],
    "email": ["email"],
    "status": ["status", "approval status", "checked in", "check-in"],
    "source_type": ["source", "how did you hear", "utm_source", "referral source"],
    "referring_ambassador_name": ["referred by", "referrer", "ambassador"],
    "job_role": ["role", "job title", "title"],
    "company": ["company", "organization", "employer"],
    "year_of_study": ["year of study", "year", "class year"],
    "degree": ["degree", "major", "field of study", "program"],
    "is_alumnus": ["alumni", "alumnus"],
}


def suggest_column_map(csv_columns: list[str]) -> dict[str, str]:
    """Best-effort default mapping based on header text, for UI convenience."""
    mapping = {f: NONE_CHOICE for f in TARGET_FIELDS}
    lowered = {c: c.lower().strip() for c in csv_columns}
    for field, hints in _AUTO_SUGGEST.items():
        for col, low in lowered.items():
            if any(hint in low for hint in hints):
                mapping[field] = col
                break
    return mapping


def unique_values(series: pd.Series) -> list[str]:
    return sorted({str(v).strip() for v in series.dropna().unique() if str(v).strip() != ""})


def suggest_status_map(values: list[str]) -> dict[str, str]:
    out = {}
    for v in values:
        low = v.lower()
        if any(k in low for k in ["attend", "checked in", "check-in", "present", "yes"]) and "not" not in low:
            out[v] = "attended"
        else:
            out[v] = "did not attend"
    return out


def suggest_source_map(values: list[str]) -> dict[str, str]:
    out = {}
    for v in values:
        low = v.lower()
        if any(k in low for k in ["ambassador", "referral", "friend", "student"]):
            out[v] = "student_ambassador"
        elif any(k in low for k in ["instagram", "twitter", "x.com", "linkedin", "facebook", "tiktok", "social"]):
            out[v] = "social_media"
        else:
            out[v] = "other"
    return out


def parse_bool(value) -> bool | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ("", "nan", "none", "unknown", "n/a"):
        return None
    if s in ("yes", "y", "true", "1", "alum", "alumnus", "alumna"):
        return True
    if s in ("no", "n", "false", "0"):
        return False
    return None


def _cell(row, column_map, field):
    col = column_map.get(field, NONE_CHOICE)
    if col == NONE_CHOICE:
        return None
    val = row.get(col)
    if pd.isna(val):
        return None
    val = str(val).strip()
    return val or None


def preview_members(conn, data: pd.DataFrame, column_map: dict[str, str]) -> dict:
    """Dry-run (no DB writes) classification of file rows by email: which
    would be newly created vs. which match an existing member. Used to
    build an import preview, including the sync/removal comparison."""
    to_create: dict[str, str] = {}
    to_update: dict[str, str] = {}
    for _, row in data.iterrows():
        email = _cell(row, column_map, "email")
        if not email:
            continue
        email = email.lower()
        if email in to_create or email in to_update:
            continue
        name = _cell(row, column_map, "name") or email
        existing = conn.execute("SELECT 1 FROM members WHERE lower(email) = ?", (email,)).fetchone()
        if existing:
            to_update[email] = name
        else:
            to_create[email] = name
    return {
        "to_create": [{"name": n, "email": e} for e, n in to_create.items()],
        "to_update": [{"name": n, "email": e} for e, n in to_update.items()],
        "file_emails": set(to_create) | set(to_update),
    }


def import_attendance_csv(
    conn, data: pd.DataFrame, column_map: dict[str, str], value_maps: dict[str, dict[str, str]],
    event_id: int,
) -> dict:
    """Create/update members and attendance rows for one event from a
    mapped Luma-style export. Duplicate (member, event) attendance rows are
    skipped. Returns an import summary for display."""
    summary = {
        "members_created": 0, "members_updated": 0,
        "attendance_created": 0, "attendance_skipped_duplicate": 0,
        "rows_skipped_no_email": 0, "unmatched_ambassador_names": set(),
    }
    status_map = value_maps.get("status", {})
    source_map = value_maps.get("source_type", {})

    for _, row in data.iterrows():
        email = _cell(row, column_map, "email")
        if not email:
            summary["rows_skipped_no_email"] += 1
            continue
        email = email.lower()
        name = _cell(row, column_map, "name") or email
        job_role = _cell(row, column_map, "job_role")
        company = _cell(row, column_map, "company")
        year_of_study = _cell(row, column_map, "year_of_study")
        degree = _cell(row, column_map, "degree")
        is_alumnus_raw = _cell(row, column_map, "is_alumnus")
        is_alumnus = parse_bool(is_alumnus_raw) if is_alumnus_raw is not None else None

        status_raw = _cell(row, column_map, "status")
        status = status_map.get(status_raw, "attended") if status_raw else "attended"
        source_raw = _cell(row, column_map, "source_type")
        source_type = source_map.get(source_raw, "other") if source_raw else "other"

        referring_name = _cell(row, column_map, "referring_ambassador_name")

        existing = conn.execute(
            "SELECT * FROM members WHERE lower(email) = ?", (email,)
        ).fetchone()

        ambassador_match = conn.execute(
            "SELECT * FROM ambassadors WHERE lower(email) = ?", (email,)
        ).fetchone()

        inferred_type = db.infer_member_type(job_role, year_of_study, degree)

        if existing is None:
            member_type = inferred_type or "non-student"
            f_job_role, f_company, f_year, f_degree, f_is_alumnus = db.type_specific_fields(
                member_type, job_role, company, year_of_study, degree, is_alumnus
            )
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
            summary["members_created"] += 1
        else:
            member_id = existing["member_id"]
            member_type = inferred_type or existing["member_type"]
            new_name = name or existing["name"]
            new_job_role = job_role if job_role is not None else existing["job_role"]
            new_company = company if company is not None else existing["company"]
            new_year = year_of_study if year_of_study is not None else existing["year_of_study"]
            new_degree = degree if degree is not None else existing["degree"]
            new_is_alumnus = existing["is_alumnus"] if is_alumnus is None else int(is_alumnus)
            f_job_role, f_company, f_year, f_degree, f_is_alumnus = db.type_specific_fields(
                member_type, new_job_role, new_company, new_year, new_degree,
                None if new_is_alumnus is None else bool(new_is_alumnus),
            )
            new_is_ambassador = 1 if ambassador_match else existing["is_ambassador"]
            new_ambassador_id = ambassador_match["ambassador_id"] if ambassador_match else existing["ambassador_id"]
            conn.execute(
                """UPDATE members SET name=?, member_type=?, job_role=?, company=?,
                   year_of_study=?, degree=?, is_alumnus=?, is_ambassador=?, ambassador_id=?
                   WHERE member_id=?""",
                (
                    new_name, member_type, f_job_role, f_company, f_year, f_degree,
                    None if f_is_alumnus is None else int(f_is_alumnus),
                    new_is_ambassador, new_ambassador_id, member_id,
                ),
            )
            summary["members_updated"] += 1

        if ambassador_match is not None and ambassador_match["member_id"] is None:
            conn.execute(
                "UPDATE ambassadors SET member_id = ? WHERE ambassador_id = ?",
                (member_id, ambassador_match["ambassador_id"]),
            )

        referring_ambassador_id = None
        if referring_name:
            amb = conn.execute(
                "SELECT * FROM ambassadors WHERE lower(name) = ?", (referring_name.lower(),)
            ).fetchone()
            if amb:
                referring_ambassador_id = amb["ambassador_id"]
            else:
                summary["unmatched_ambassador_names"].add(referring_name)

        dup = conn.execute(
            "SELECT 1 FROM attendance WHERE member_id = ? AND event_id = ?", (member_id, event_id)
        ).fetchone()
        if dup:
            summary["attendance_skipped_duplicate"] += 1
            continue

        conn.execute(
            """INSERT INTO attendance (member_id, event_id, status, source_type, referring_ambassador_id)
               VALUES (?, ?, ?, ?, ?)""",
            (member_id, event_id, status, source_type, referring_ambassador_id),
        )
        summary["attendance_created"] += 1

    conn.commit()
    return summary
