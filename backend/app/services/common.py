"""Shared helpers: settings, audit log, notifications, normalisation, pagination."""
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import utcnow
from ..models import AllocationCycle, AuditLog, Notification, SystemSetting

DEFAULT_SETTINGS: dict[str, tuple[Any, str]] = {
    "min_team_size": (2, "Minimum number of students in a team (leader included)."),
    "max_team_size": (4, "Maximum number of students in a team (leader included)."),
    "allow_cross_department": (False, "Allow team members from a different department than the team's."),
    "allow_cross_programme": (False, "Allow team members from a different degree/programme than the team's."),
    "allowed_email_domains": ("", "Comma-separated institutional e-mail domains (empty = any domain)."),
    "restrict_faculty_to_team_department": (False, "Only allocate faculty from the same department as the team."),
    "min_compatibility_score": (20, "Legacy setting kept for compatibility. Compatibility is now decided by the domain tiers "
                                    "(primary, additional, related); this value no longer affects allocation."),
    "min_faculty_capacity": (1, "Smallest project capacity an administrator may set for a faculty member (0 would block all new teams)."),
    "max_faculty_capacity": (100, "Largest project capacity an administrator may set for a faculty member."),
    "default_faculty_capacity": (10, "Capacity suggested when no designation default applies."),
    "designation_capacity_defaults": (
        {"HOD": 5, "Project Coordinator": 6, "Professor": 10, "Associate Professor": 10, "Assistant Professor": 10},
        "Editable SUGGESTIONS for faculty capacity by designation (admin-set capacity always wins)."),
}


def get_setting(db: Session, key: str):
    row = db.get(SystemSetting, key)
    if row is not None:
        return row.value
    return DEFAULT_SETTINGS[key][0]


def all_settings(db: Session) -> dict[str, Any]:
    return {k: get_setting(db, k) for k in DEFAULT_SETTINGS}


def audit(db: Session, actor_id: int | None, action: str, entity_type: str, entity_id: int | None = None,
          details: dict | None = None) -> None:
    db.add(AuditLog(actor_user_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id,
                    details=details, created_at=utcnow()))


def notify(db: Session, user_id: int, title: str, message: str, kind: str = "info") -> None:
    db.add(Notification(user_id=user_id, title=title, message=message, kind=kind))


def norm_email(v: str) -> str:
    return v.strip().lower()


def norm_regno(v: str) -> str:
    return re.sub(r"\s+", "", v.strip()).upper()


# Register number: RA + 2-digit batch + fixed department code 11003040 + 3-digit student number (001-999).
REGNO_RE = re.compile(r"^RA(\d{2})11003040(?!000)(\d{3})$")
REGNO_MESSAGE = ("Invalid register number. Use the format RA{BATCH}11003040{NNN} - 'RA', a two-digit batch year, "
                 "the fixed code 11003040 and a three-digit student number starting from 001 (e.g. RA2311003040001).")


def is_valid_regno(v: str) -> bool:
    return bool(REGNO_RE.fullmatch(norm_regno(v or "")))


def validate_regno(v: str) -> str:
    """Normalise and validate a register number; raise ValueError with a clear message if the format is wrong."""
    n = norm_regno(v or "")
    if not REGNO_RE.fullmatch(n):
        raise ValueError(REGNO_MESSAGE)
    return n


# Institutional e-mail: registrations (team leaders, team members, faculty) must use this exact domain.
INSTITUTIONAL_EMAIL_DOMAIN = "srmist.edu.in"


def check_institutional_email(email: str) -> str:
    """Normalise the address, then require the exact @srmist.edu.in domain (any username is accepted).
    Raises HTTP 422 with a clear message otherwise; returns the normalised address."""
    n = norm_email(email or "")
    local, _, domain = n.rpartition("@")
    if not local or domain != INSTITUTIONAL_EMAIL_DOMAIN:
        raise HTTPException(422, f"'{n or email}' is not allowed. Use your institutional e-mail address "
                                 f"ending in @{INSTITUTIONAL_EMAIL_DOMAIN}.")
    return n


def norm_name(v: str) -> str:
    return re.sub(r"\s+", " ", v.strip())


def paginate(db: Session, stmt, page: int, page_size: int, unique: bool = False):
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    result = db.execute(stmt.limit(page_size).offset((page - 1) * page_size))
    items = result.unique().scalars().all() if unique else result.scalars().all()
    return {"total": total or 0, "page": page, "page_size": page_size, "items": items}


def like(term: str) -> str:
    esc = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc}%"


def active_cycle(db: Session, required: bool = True) -> AllocationCycle | None:
    cyc = db.scalar(select(AllocationCycle).where(AllocationCycle.active_marker == 1))
    if cyc is None and required:
        raise HTTPException(409, "No allocation cycle is active. An administrator must activate one.")
    return cyc


def get_cycle(db: Session, cycle_id: int | None) -> AllocationCycle:
    if cycle_id is None:
        return active_cycle(db)
    cyc = db.get(AllocationCycle, cycle_id)
    if not cyc:
        raise HTTPException(404, "Allocation cycle not found.")
    return cyc
