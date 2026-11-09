"""Faculty capacity and workload.

Capacity is counted in TEAM PROJECTS per allocation cycle (not students).
A faculty member supervising one team of four students uses ONE unit of capacity.
"""
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (FAC_APPROVED, P_APPROVED, P_ALLOCATED, P_FINALISED, Allocation, AllocationCycle, CapacityChange,
                      FacultyCycleCapacity, FacultyProfile, Proposal, Team)
from .common import audit, get_setting, notify


def capacity_map(db: Session, cycle_id: int) -> dict[int, int]:
    return {r.faculty_id: r.max_capacity for r in db.scalars(
        select(FacultyCycleCapacity).where(FacultyCycleCapacity.cycle_id == cycle_id))}


def assigned_counts(db: Session, cycle_id: int, exclude_team_ids=()) -> dict[int, int]:
    """Teams per faculty in a cycle. ``exclude_team_ids`` leaves out teams that are being re-decided, so one assignment
    is never counted twice (as existing load AND as a new proposed assignment)."""
    stmt = select(Allocation.faculty_id, func.count()).where(Allocation.cycle_id == cycle_id)
    if exclude_team_ids:
        stmt = stmt.where(Allocation.team_id.not_in(list(exclude_team_ids)))
    return {fid: n for fid, n in db.execute(stmt.group_by(Allocation.faculty_id)).all()}


def capacity_limits(db: Session) -> dict:
    """Configured bounds for a faculty member's capacity (settings: min/max_faculty_capacity)."""
    return {"min": int(get_setting(db, "min_faculty_capacity")), "max": int(get_setting(db, "max_faculty_capacity"))}


def validate_capacity(db: Session, value, field: str = "capacity") -> int:
    """Single source of truth for capacity validation (approval and edits). Rejects non-integers, decimals, booleans
    and values outside the configured range with a field-level error the UI shows next to the input."""
    lim = capacity_limits(db)

    def fail(msg):
        raise HTTPException(422, {"code": "validation_error", "message": f"{field}: {msg}",
                                  "errors": [{"field": field, "message": msg}], "limits": lim})
    if value is None or (isinstance(value, str) and not value.strip()):
        fail("Enter the maximum number of projects this faculty member can supervise.")
    if isinstance(value, bool) or not isinstance(value, int):
        fail("Capacity must be a whole number (no decimals or text).")
    if value < lim["min"]:
        fail(f"Capacity must be at least {lim['min']}." if lim["min"] > 0 else "Capacity cannot be negative.")
    if value > lim["max"]:
        fail(f"Capacity cannot be more than {lim['max']}.")
    return value


def effective_capacity(db: Session, fac: FacultyProfile, cycle_id: int) -> int:
    row = db.scalar(select(FacultyCycleCapacity.max_capacity).where(
        FacultyCycleCapacity.faculty_id == fac.id, FacultyCycleCapacity.cycle_id == cycle_id))
    return fac.max_capacity if row is None else row


def ineligibility_reason(fac: FacultyProfile, capacity: int, assigned: int) -> str | None:
    """Status/capacity rules for receiving a NEW assignment (domain rules are checked separately)."""
    if fac.approval_status != FAC_APPROVED:
        return f"registration is {fac.approval_status}"
    if not fac.user.is_active:
        return "account is deactivated"
    if not fac.is_available:
        return "marked unavailable"
    if capacity <= 0:
        return "capacity is zero"
    return None      # nominal capacity is no longer a hard barrier: controlled overload is allowed (see allocation.py)


def faculty_rows(db: Session, cycle: AllocationCycle, only_approved: bool = False) -> list[dict]:
    caps, counts = capacity_map(db, cycle.id), assigned_counts(db, cycle.id)
    stmt = select(FacultyProfile).order_by(FacultyProfile.id)
    if only_approved:
        stmt = stmt.where(FacultyProfile.approval_status == FAC_APPROVED)
    rows = []
    for f in db.scalars(stmt).unique():
        cap = caps.get(f.id, f.max_capacity)
        n = counts.get(f.id, 0)
        reason = ineligibility_reason(f, cap, n)
        rows.append({"id": f.id, "name": f.user.full_name, "email": f.user.email, "employee_id": f.employee_id,
                     "department": f.department, "designation": f.designation,
                     "approval_status": f.approval_status, "is_active": f.user.is_active,
                     "is_available": f.is_available, "max_capacity": cap, "assigned": n,
                     "remaining": max(0, cap - n), "over_capacity": n > cap, "overload": max(0, n - cap),
                     "load_ratio": round(n / cap, 3) if cap > 0 else None,
                     "eligible_for_allocation": reason is None, "ineligible_reason": reason})
    return rows


def team_pool(db: Session, cycle_id: int):
    """Teams of the cycle whose proposal is approved + marked eligible, split by allocation state."""
    teams = list(db.scalars(select(Team).join(Proposal, Proposal.team_id == Team.id).where(
        Team.cycle_id == cycle_id, Proposal.eligible_for_allocation == True,  # noqa: E712
        Proposal.status.in_([P_APPROVED, P_ALLOCATED, P_FINALISED])).order_by(Team.id)).unique())
    eligible_total = len(teams)
    unallocated = [t for t in teams if t.allocation is None and t.proposal.status == P_APPROVED]
    return eligible_total, unallocated


def summary(db: Session, cycle: AllocationCycle) -> dict:
    rows = faculty_rows(db, cycle, only_approved=True)
    eligible_total, unalloc = team_pool(db, cycle.id)
    n_unalloc = len(unalloc)
    elig = [r for r in rows if r["approval_status"] == FAC_APPROVED and r["is_active"] and r["is_available"]]
    with_room = [r for r in elig if r["remaining"] > 0]
    overloaded = [r for r in rows if r["over_capacity"]]
    total_capacity = sum(r["max_capacity"] for r in elig)
    available = sum(r["remaining"] for r in elig)
    existing = sum(r["assigned"] for r in rows)
    baseline = round(n_unalloc / len(elig), 2) if elig else None
    cap_baseline = round(n_unalloc / len(with_room), 2) if with_room else None
    return {
        "cycle": {"id": cycle.id, "name": cycle.name, "status": cycle.status},
        "eligible_teams_total": eligible_total,
        "teams_requiring_guides": n_unalloc,
        "eligible_faculty": len(elig),
        "faculty_with_remaining_capacity": len(with_room),
        "existing_allocations": existing,
        "remaining_eligible_teams": n_unalloc,
        "estimated_baseline": baseline,
        "capacity_aware_baseline": cap_baseline,
        "total_capacity": total_capacity,
        "overloaded_faculty": len(overloaded),
        "total_overload": sum(r["overload"] for r in overloaded),
        "capacity_limits": capacity_limits(db),
        "available_capacity": available,
        "capacity_shortage": max(0, n_unalloc - available),
        "capacity_surplus": max(0, available - n_unalloc),
        "explanation": (
            "Simple baseline = eligible unallocated team projects ÷ eligible faculty members. It is a planning estimate, "
            "not a quota. The optimiser balances relative workload (load ÷ capacity) across compatible mentors. When "
            "demand exceeds capacity every team still receives a mentor and the unavoidable overload is spread as evenly as possible."),
        "faculty": rows,
    }


def set_capacity(db: Session, admin_id: int, fac: FacultyProfile, cycle: AllocationCycle, new_cap: int,
                 reason: str, confirm_below: bool, expected_current: int | None = None) -> dict:
    new_cap = validate_capacity(db, new_cap, "max_capacity")
    # lock the faculty row so concurrent capacity edits / allocations serialise
    db.execute(select(FacultyProfile.id).where(FacultyProfile.id == fac.id).with_for_update())
    old = effective_capacity(db, fac, cycle.id)
    if expected_current is not None and expected_current != old:
        raise HTTPException(409, {"code": "capacity_changed", "current_capacity": old,
                                  "message": f"The capacity was changed to {old} by someone else while you were editing. "
                                             "Reload and review before saving."})
    assigned = assigned_counts(db, cycle.id).get(fac.id, 0)
    if new_cap < assigned and not confirm_below:
        raise HTTPException(409, {
            "code": "capacity_below_assigned",
            "message": (f"{fac.user.full_name} currently supervises {assigned} team(s). Setting capacity to {new_cap} is "
                        f"below that, which means {assigned - new_cap} team(s) of overload. Existing assignments will NOT be removed "
                        f"or reassigned automatically. The optimiser will avoid giving this member more teams, but may "
                        f"still do so when no other compatible mentor can take them. Confirm to continue."),
            "assigned": assigned, "old_capacity": old, "new_capacity": new_cap, "overload": assigned - new_cap})
    row = db.scalar(select(FacultyCycleCapacity).where(FacultyCycleCapacity.faculty_id == fac.id,
                                                       FacultyCycleCapacity.cycle_id == cycle.id))
    if row is None:
        db.add(FacultyCycleCapacity(faculty_id=fac.id, cycle_id=cycle.id, max_capacity=new_cap))
    else:
        row.max_capacity = new_cap
    if cycle.is_active:
        fac.max_capacity = new_cap  # default for cycles that have no explicit row yet
    db.add(CapacityChange(faculty_id=fac.id, cycle_id=cycle.id, old_capacity=old, new_capacity=new_cap,
                          assigned_at_change=assigned, reason=reason, changed_by=admin_id))
    audit(db, admin_id, "faculty.capacity_change", "faculty", fac.id,
          {"old": old, "new": new_cap, "assigned": assigned, "reason": reason, "cycle_id": cycle.id})
    notify(db, fac.user_id, "Project capacity updated",
           f"Your project capacity for {cycle.name} was changed from {old} to {new_cap} team(s).", "capacity")
    db.commit()
    return {"old_capacity": old, "new_capacity": new_cap, "assigned": assigned, "over_capacity": assigned > new_cap,
            "overload": max(0, assigned - new_cap)}


def suggested_capacity(db: Session, designation: str) -> int:
    defaults = get_setting(db, "designation_capacity_defaults") or {}
    for k, v in defaults.items():
        if k.lower() == designation.lower():
            return int(v)
    return int(get_setting(db, "default_faculty_capacity"))
