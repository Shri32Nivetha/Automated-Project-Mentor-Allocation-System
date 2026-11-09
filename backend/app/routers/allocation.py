from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_admin
from ..models import Allocation, AllocationPreview, FacultyProfile, Team, User
from ..schemas import CommitIn, FinaliseIn, ManualIn, PreviewIn, UnassignIn
from ..services import allocation as alloc
from ..services import workload as wl
from ..services.common import get_cycle, paginate

router = APIRouter(prefix="/admin", tags=["allocation"], dependencies=[Depends(require_admin)])


@router.get("/workload")
def workload(cycle_id: int | None = None, db: Session = Depends(get_db)):
    return wl.summary(db, get_cycle(db, cycle_id))


def _preview_out(p: AllocationPreview) -> dict:
    return {"id": p.id, "cycle_id": p.cycle_id, "status": p.status, "created_at": p.created_at,
            "committed_at": p.committed_at, **p.payload, "result": p.result}


@router.post("/allocation/preview", status_code=201)
def preview(data: PreviewIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return _preview_out(alloc.build_preview(db, admin, get_cycle(db, data.cycle_id), data.reoptimize, data.include_manual))


@router.get("/allocation/preview/{pid}")
def get_preview(pid: int, db: Session = Depends(get_db)):
    p = db.get(AllocationPreview, pid)
    if not p:
        raise HTTPException(404, "Preview not found.")
    return _preview_out(p)


@router.post("/allocation/preview/{pid}/commit")
def commit(pid: int, data: CommitIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return alloc.commit_preview(db, admin, pid, data.confirm, data.acknowledge_overload)


@router.get("/allocation")
def list_allocations(page: int = 1, page_size: int = 25, cycle_id: int | None = None, db: Session = Depends(get_db)):
    cyc = get_cycle(db, cycle_id)
    r = paginate(db, select(Allocation).where(Allocation.cycle_id == cyc.id).order_by(Allocation.id), page, page_size,
                 unique=True)
    items = []
    for a in r["items"]:
        t = db.get(Team, a.team_id)
        items.append({"id": a.id, "team_id": t.id, "team_name": t.name, "project_title": t.proposal.title,
                      "faculty_id": a.faculty_id, "faculty_name": a.faculty.user.full_name, "status": a.status,
                      "method": a.method, "score": a.score, "explanation": a.explanation, "created_at": a.created_at,
                      "match_tier": a.match_tier, "matched_domains": a.matched_domains, "is_override": a.is_override,
                      "override_reason": a.override_reason, "auto_recommendation": a.auto_recommendation})
    r["items"] = items
    return r


@router.get("/allocation/unallocated")
def unallocated(cycle_id: int | None = None, db: Session = Depends(get_db)):
    """Teams of the cycle without a guide, each with the reason (computed with the same rules as the engine)."""
    cyc = get_cycle(db, cycle_id)
    teams = list(db.scalars(select(Team).where(Team.cycle_id == cyc.id).order_by(Team.id)).unique())
    parents, names = alloc.load_parents(db)
    restrict = alloc.restrict_department(db)
    facs = alloc.fac_views(db, cyc.id)
    out = []
    for t in teams:
        if t.allocation is not None:
            continue
        p = t.proposal
        suggestions, code = [], None
        if p is None or p.status == "draft":
            reason = "Proposal has not been submitted."
        elif p.status in ("submitted", "under_review"):
            reason = "Proposal is awaiting admin review."
        elif p.status == "needs_revision":
            reason = "Proposal needs revision."
        elif p.status == "rejected":
            reason = "Proposal was rejected."
        elif not p.eligible_for_allocation:
            reason = "Team is marked ineligible for allocation."
        else:
            tv = alloc.team_view(t)
            if any(f.status_problem is None and f.capacity > 0 and alloc.match_pair(tv, f, parents, names, restrict)["compatible"]
                   for f in facs):
                reason, code = "Eligible and a compatible mentor exists - run the allocation preview.", "ready"
            else:
                r = alloc._unresolved(tv, facs, parents, names, restrict)
                reason, code, suggestions = r["reason"], r["code"], r["suggestions"]
        out.append({"team_id": t.id, "team_name": t.name, "project_title": p.title if p else "",
                    "proposal_status": p.status if p else None, "reason": reason, "code": code,
                    "requires_resolution": code in ("no_compatible_domain", "no_eligible_faculty", "department_restriction"),
                    "suggestions": suggestions})
    return out


@router.get("/allocation/candidates/{team_id}")
def candidates(team_id: int, db: Session = Depends(get_db)):
    t = db.get(Team, team_id)
    if not t:
        raise HTTPException(404, "Team not found.")
    return {"team": {"id": t.id, "name": t.name, "project_title": t.proposal.title,
                     "current_faculty": t.allocation.faculty.user.full_name if t.allocation else None,
                     "status": t.allocation.status if t.allocation else None},
            "faculty": alloc.eligible_faculty_for_team(db, t)}


@router.get("/allocation/manual-preview")
def manual_preview(team_id: int, faculty_id: int, db: Session = Depends(get_db)):
    t, f = db.get(Team, team_id), db.get(FacultyProfile, faculty_id)
    if not t or not f:
        raise HTTPException(404, "Team or faculty member not found.")
    return alloc.manual_check(db, t, f)


@router.post("/allocation/manual")
def manual(data: ManualIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    a = alloc.assign_manual(db, admin, data.team_id, data.faculty_id, data.reason, data.confirm,
                            data.override_domain, data.acknowledge_overload)
    return {"allocation_id": a.id, "team_id": a.team_id, "faculty_id": a.faculty_id, "status": a.status,
            "is_override": a.is_override, "match_tier": a.match_tier}


@router.post("/allocation/unassign")
def unassign(data: UnassignIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    alloc.unassign(db, admin, data.team_id, data.reason, data.confirm)
    return {"ok": True}


@router.post("/allocation/finalise")
def finalise(data: FinaliseIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    cyc = get_cycle(db, data.cycle_id)
    return alloc.finalise_cycle(db, admin, cyc.id, data.confirm, data.acknowledge_overload)
