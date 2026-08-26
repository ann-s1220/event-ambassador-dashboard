"""Excel (.xlsx) imports: bulk member create/update by email (no
attendance records), and ambassador social-media post logs matched
against the existing roster/event list. Same column-mapping pattern as
the Luma CSV import in csv_import.py; member create/update and the
sync/removal comparison reuse that module's helpers directly."""
import pandas as pd

import db
from csv_import import NONE_CHOICE, parse_bool

MEMBER_TARGET_FIELDS = [
    "name", "email", "member_type", "job_role", "company",
    "is_alumnus", "year_of_study", "degree",
]
MEMBER_REQUIRED_FIELDS = {"name", "email"}
MEMBER_TYPE_VALUES = ["student", "non-student"]

_MEMBER_AUTO_SUGGEST = {
    "name": ["full name", "name"],
    "email": ["email"],
    "member_type": ["member type", "type", "student status"],
    "job_role": ["role", "job title", "title"],
    "company": ["company", "organization", "employer"],
    "is_alumnus": ["alumni", "alumnus"],
    "year_of_study": ["year of study", "year", "class year"],
    "degree": ["degree", "major", "field of study", "program"],
}

POST_TARGET_FIELDS = ["ambassador_email", "ambassador_name", "event_name", "date_posted"]

_POST_AUTO_SUGGEST = {
    "ambassador_email": ["ambassador email", "email"],
    "ambassador_name": ["ambassador name", "ambassador", "name"],
    "event_name": ["event name", "event"],
    "date_posted": ["date posted", "date", "posted"],
}


def _cell(row, column_map, field):
    """Mapped column's value for this row as a stripped string, or None."""
    col = column_map.get(field, NONE_CHOICE)
    if col == NONE_CHOICE:
        return None
    val = row.get(col)
    if pd.isna(val):
        return None
    val = str(val).strip()
    return val or None


def _raw_cell(row, column_map, field):
    """Mapped column's value for this row with no string conversion (dates,
    in particular, parse better from pandas' native Timestamp than from a
    reformatted string)."""
    col = column_map.get(field, NONE_CHOICE)
    if col == NONE_CHOICE:
        return None
    val = row.get(col)
    if pd.isna(val):
        return None
    return val


def _parse_date(value):
    if value is None:
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.date()


def suggest_member_column_map(columns: list[str]) -> dict[str, str]:
    mapping = {f: NONE_CHOICE for f in MEMBER_TARGET_FIELDS}
    lowered = {c: c.lower().strip() for c in columns}
    used = set()
    for field, hints in _MEMBER_AUTO_SUGGEST.items():
        for col, low in lowered.items():
            if col in used:
                continue
            if any(hint in low for hint in hints):
                mapping[field] = col
                used.add(col)
                break
    return mapping


def suggest_member_type_map(values: list[str]) -> dict[str, str]:
    out = {}
    for v in values:
        low = v.lower()
        # Check "non" first -- "non-student" contains "student" as a
        # substring, so a plain "student" in low check would misclassify it.
        out[v] = "non-student" if "non" in low else ("student" if "student" in low else "non-student")
    return out


def suggest_post_column_map(columns: list[str]) -> dict[str, str]:
    mapping = {f: NONE_CHOICE for f in POST_TARGET_FIELDS}
    lowered = {c: c.lower().strip() for c in columns}
    used = set()
    for field, hints in _POST_AUTO_SUGGEST.items():
        for col, low in lowered.items():
            if col in used:
                continue
            if any(hint in low for hint in hints):
                mapping[field] = col
                used.add(col)
                break
    return mapping


def import_members_excel(conn, data: pd.DataFrame, column_map: dict[str, str], member_type_map: dict[str, str]) -> dict:
    """Create/update members by email from a mapped Excel file. Never
    touches attendance -- members only."""
    summary = {"members_created": 0, "members_updated": 0, "rows_skipped_no_email": 0}

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

        member_type_raw = _cell(row, column_map, "member_type")
        mapped_type = member_type_map.get(member_type_raw) if member_type_raw else None
        inferred_type = db.infer_member_type(job_role, year_of_study, degree)

        existing = conn.execute("SELECT * FROM members WHERE lower(email) = ?", (email,)).fetchone()
        ambassador_match = conn.execute("SELECT * FROM ambassadors WHERE lower(email) = ?", (email,)).fetchone()

        if existing is None:
            member_type = mapped_type or inferred_type or "non-student"
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
            member_type = mapped_type or inferred_type or existing["member_type"]
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

    conn.commit()
    return summary


def preview_posts(conn, data: pd.DataFrame, column_map: dict[str, str]) -> dict:
    """Dry-run match of each row's ambassador (by email, falling back to
    name) and event (by name). Rows with no ambassador or event match, or
    an unparseable/missing date, land in `unmatched` with a reason instead
    of being silently dropped."""
    matched, unmatched = [], []

    for i, row in data.iterrows():
        email = _cell(row, column_map, "ambassador_email")
        amb_name = _cell(row, column_map, "ambassador_name")
        event_name = _cell(row, column_map, "event_name")
        date_raw = _raw_cell(row, column_map, "date_posted")
        date_val = _parse_date(date_raw)

        reasons = []
        ambassador = db.find_ambassador_by_email(conn, email) if email else None
        if ambassador is None and amb_name:
            ambassador = db.find_ambassador_by_name(conn, amb_name)
        if ambassador is None:
            if not email and not amb_name:
                reasons.append("missing ambassador email/name")
            else:
                reasons.append(f"no ambassador found for '{email or amb_name}'")

        event = None
        if not event_name:
            reasons.append("missing event name")
        else:
            event = conn.execute(
                "SELECT * FROM events WHERE lower(name) = ?", (event_name.strip().lower(),)
            ).fetchone()
            if event is None:
                reasons.append(f"no event found named '{event_name}'")

        if date_raw is None:
            reasons.append("missing date posted")
        elif date_val is None:
            reasons.append(f"unparseable date '{date_raw}'")

        row_out = {
            "row": i + 2,  # +1 for 0-index, +1 for the header row -- matches the spreadsheet's own row numbers
            "ambassador_email": email or "",
            "ambassador_name": ambassador["name"] if ambassador else (amb_name or ""),
            "event_name": event_name or "",
            "date_posted": date_val.isoformat() if date_val else (str(date_raw) if date_raw is not None else ""),
        }
        if reasons:
            row_out["reason"] = "; ".join(reasons)
            unmatched.append(row_out)
        else:
            row_out["ambassador_id"] = ambassador["ambassador_id"]
            row_out["event_id"] = event["event_id"]
            matched.append(row_out)

    return {"matched": matched, "unmatched": unmatched}


def import_posts_excel(conn, matched_rows: list[dict]) -> int:
    for r in matched_rows:
        conn.execute(
            "INSERT INTO ambassador_social_posts (ambassador_id, event_id, date_posted) VALUES (?, ?, ?)",
            (r["ambassador_id"], r["event_id"], r["date_posted"]),
        )
    conn.commit()
    return len(matched_rows)
