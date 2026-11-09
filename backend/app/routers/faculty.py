"""Endpoints for the logged-in faculty member (own profile and own assigned teams only)."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import faculty_profile, require_faculty
from ..models import Allocation, FacultyProfile, Team, User
from ..schemas import FacultyProfileUpdateIn
from ..services import faculty as fsvc
from ..services import teams as tsvc
from ..services import workload as wl
from ..services.common import active_cycle, audit

router = APIRouter(prefix="/faculty/me", tags=["faculty"])


def profile_dict(db: Session, p: FacultyProfile) -> dict:
    cyc = active_cycle(db, required=False)
    w = None
    if cyc:
        cap, n = wl.effective_capacity(db, p, cyc.id), wl.assigned_counts(db, cyc.id).get(p.id, 0)
        w = {"cycle": {"id": cyc.id, "name": cyc.name}, "max_capacity": cap, "assigned": n, "remaining": max(0, cap - n),
             "over_capacity": n > cap, "can_receive_new": wl.ineligibility_reason(p, cap, n) is None,
             "ineligible_reason": wl.ineligibility_reason(p, cap, n)}
    return {"id": p.id, "full_name": p.user.full_name, "email": p.user.email, "employee_id": p.employee_id,
            "department": p.department, "designation": p.designation, "approval_status": p.approval_status,
            "approval_remarks": p.approval_remarks, "is_active": p.user.is_active, "is_available": p.is_available,
            "additional_interests": p.additional_interests, "domains": fsvc.serialize_faculty_domains(p),
            "workload": w, "capacity_note": "Only an administrator can change your capacity."}


@router.get("")
def me(p: FacultyProfile = Depends(faculty_profile), db: Session = Depends(get_db)):
    return profile_dict(db, p)


@router.put("")
def update_me(data: FacultyProfileUpdateIn, p: FacultyProfile = Depends(faculty_profile),
              user: User = Depends(require_faculty), db: Session = Depends(get_db)):
    ch = data.model_dump(exclude_unset=True)
    fsvc.set_faculty_domains(db, p, ch.get("expertise_domain_ids"), ch.get("supported_domain_ids"),
                             ch.get("interest_domain_ids"), ch.get("custom_domain_name"), user.id)
    if ch.get("full_name"):
        user.full_name = ch["full_name"]
    for k in ("department", "additional_interests", "is_available"):
        if ch.get(k) is not None:
            setattr(p, k, ch[k])
    audit(db, user.id, "faculty.profile_update", "faculty", p.id, {"fields": list(ch)})
    db.commit()
    db.expire_all()
    return profile_dict(db, db.get(FacultyProfile, p.id))


@router.get("/teams")
def my_teams(p: FacultyProfile = Depends(faculty_profile), db: Session = Depends(get_db)):
    """Teams assigned to this faculty member (all cycles, newest first) incl. members and proposals."""
    if p.approval_status != "approved":
        return []
    allocs = db.scalars(select(Allocation).where(Allocation.faculty_id == p.id).order_by(Allocation.id.desc())).unique().all()
    out = []
    for a in allocs:
        t = db.get(Team, a.team_id)
        d = tsvc.serialize_team(t)
        out.append({"allocation_status": a.status, "assigned_at": a.created_at, "cycle": d["cycle"],
                    "team": {"id": t.id, "name": t.name, "department": t.department, "programme": t.programme,
                             "year_semester": t.year_semester, "leader": d["leader"], "members": d["members"]},
                    "proposal": d["proposal"]})
    return out
