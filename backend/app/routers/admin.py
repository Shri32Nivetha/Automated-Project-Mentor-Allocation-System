"""Administrator endpoints: dashboard, faculty, teams, proposals, domains, cycles, settings, audit."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, literal, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db, utcnow
from ..deps import require_admin
from ..models import (CYCLE_ACTIVE, CYCLE_FINALISED, CYCLE_PLANNED, FAC_APPROVED, FAC_PENDING, P_APPROVED, P_REVIEW,
                      P_SUBMITTED, Allocation, AllocationCycle, AllocationHistory, AuditLog, CapacityChange, Domain,
                      FacultyCycleCapacity, FacultyProfile, PasswordResetToken, Proposal, SystemSetting, Team, TeamChangeRequest,
                      TeamDomain, TeamMember, User)
from ..schemas import (AdminFacultyUpdateIn, CapacityIn, ChangeRequestResolve, CustomDomainReview, CycleIn,
                       CycleUpdate, DomainIn, DomainOut, DomainUpdate, FacultyApproveIn, FacultyDecisionIn, MemberIn, MemberUpdateIn,
                       ReviewIn, SettingsIn, TeamUpdateIn)
from ..security import new_reset_token
from ..services import allocation as alloc
from ..services import faculty as fsvc
from ..services import proposals as psvc
from ..services import teams as tsvc
from ..services import workload as wl
from ..services.common import (DEFAULT_SETTINGS, active_cycle, all_settings, audit, get_cycle, like, notify,
                               paginate)
from .faculty import profile_dict

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _sort(stmt, mapping: dict, sort: str | None, default):
    desc = bool(sort and sort.startswith("-"))
    col = mapping.get((sort or "").lstrip("-"), default)
    return stmt.order_by(col.desc() if desc else col.asc(), default.asc())


# ------------------------------------------------------------------ dashboard
@router.get("/dashboard")
def dashboard(cycle_id: int | None = None, db: Session = Depends(get_db)):
    cyc = get_cycle(db, cycle_id)
    w = wl.summary(db, cyc)
    q = lambda stmt: db.scalar(stmt) or 0
    total_teams = q(select(func.count()).select_from(Team).where(Team.cycle_id == cyc.id))
    by_status = dict(db.execute(select(Proposal.status, func.count()).join(Team, Team.id == Proposal.team_id)
                                .where(Team.cycle_id == cyc.id).group_by(Proposal.status)).all())
    allocated = q(select(func.count()).select_from(Allocation).where(Allocation.cycle_id == cyc.id))
    dom_counts = db.execute(select(Domain.name, func.count()).join(TeamDomain, TeamDomain.domain_id == Domain.id)
                            .join(Team, Team.id == TeamDomain.team_id)
                            .where(Team.cycle_id == cyc.id, TeamDomain.kind == "primary")
                            .group_by(Domain.name).order_by(func.count().desc(), Domain.name)).all()
    recent = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(10)).unique().all()
    # teams that are eligible but have NO compatible, eligible mentor: they need an administrator's decision
    parents, names = alloc.load_parents(db)
    restrict = alloc.restrict_department(db)
    facs = alloc.fac_views(db, cyc.id)
    _, pool = wl.team_pool(db, cyc.id)
    needs_resolution = sum(1 for t in pool if not any(
        f.status_problem is None and f.capacity > 0 and alloc.match_pair(alloc.team_view(t), f, parents, names, restrict)["compatible"]
        for f in facs))
    hist = db.scalars(select(AllocationHistory).where(AllocationHistory.cycle_id == cyc.id)
                      .order_by(AllocationHistory.id.desc()).limit(8)).all()
    fn = lambda fid: (db.get(FacultyProfile, fid).user.full_name if fid else None)  # noqa: E731
    return {
        "cycle": {"id": cyc.id, "name": cyc.name, "status": cyc.status, "is_active": cyc.is_active},
        "total_teams": total_teams,
        "pending_reviews": by_status.get(P_SUBMITTED, 0) + by_status.get(P_REVIEW, 0),
        "approved_teams": by_status.get("approved", 0) + by_status.get("allocated", 0) + by_status.get("finalised", 0),
        "proposal_status_counts": by_status,
        "eligible_faculty": w["eligible_faculty"],
        "pending_faculty_approvals": q(select(func.count()).select_from(FacultyProfile).where(
            FacultyProfile.approval_status == FAC_PENDING)),
        "allocated_teams": allocated,
        "unallocated_teams": max(0, total_teams - allocated),
        "teams_requiring_resolution": needs_resolution,
        "approved_faculty": q(select(func.count()).select_from(FacultyProfile).where(FacultyProfile.approval_status == FAC_APPROVED)),
        "overloaded_faculty": w["overloaded_faculty"], "total_overload": w["total_overload"],
        "recent_allocation_activity": [{"id": h.id, "action": h.action, "team": db.get(Team, h.team_id).name,
                                        "old_faculty": fn(h.old_faculty_id), "new_faculty": fn(h.new_faculty_id),
                                        "is_override": h.is_override, "domain_violation": h.domain_violation,
                                        "capacity_violation": h.capacity_violation, "reason": h.reason,
                                        "created_at": h.created_at} for h in hist],
        "total_capacity": w["total_capacity"], "remaining_capacity": w["available_capacity"],
        "capacity_shortage": w["capacity_shortage"], "teams_requiring_guides": w["teams_requiring_guides"],
        "faculty_workload": [{"id": r["id"], "name": r["name"], "assigned": r["assigned"], "capacity": r["max_capacity"],
                              "overload": r["overload"]}
                             for r in w["faculty"] if r["approval_status"] == FAC_APPROVED],
        "domain_team_counts": [{"domain": n, "teams": c} for n, c in dom_counts],
        "allocation_status": {"cycle_status": cyc.status, "finalised_at": cyc.finalised_at,
                              "pending_change_requests": q(select(func.count()).select_from(TeamChangeRequest).where(
                                  TeamChangeRequest.status == "pending"))},
        "recent_actions": [{"id": a.id, "action": a.action, "entity_type": a.entity_type, "entity_id": a.entity_id,
                            "actor": a.actor.full_name if a.actor else None, "created_at": a.created_at} for a in recent],
    }


# ------------------------------------------------------------------ faculty
@router.get("/faculty-meta")
def faculty_meta(db: Session = Depends(get_db)):
    """Lookups for the faculty screens: departments, designations and the configured capacity bounds."""
    return {"departments": sorted(d for (d,) in db.execute(select(FacultyProfile.department).distinct()) if d),
            "capacity_limits": wl.capacity_limits(db)}


@router.get("/faculty")
def list_faculty(page: int = 1, page_size: int = 20, search: str | None = None, status: str | None = None,
                 department: str | None = None, available: bool | None = None, workload: str | None = None,
                 sort: str | None = None, db: Session = Depends(get_db)):
    cyc = active_cycle(db, required=False)
    stmt = select(FacultyProfile).join(User, User.id == FacultyProfile.user_id)
    cap_col, n_col = FacultyProfile.max_capacity, literal(0)
    if cyc:
        cnt = select(Allocation.faculty_id.label("fid"), func.count().label("n")).where(
            Allocation.cycle_id == cyc.id).group_by(Allocation.faculty_id).subquery()
        cps = select(FacultyCycleCapacity.faculty_id.label("fid"), FacultyCycleCapacity.max_capacity.label("c")).where(
            FacultyCycleCapacity.cycle_id == cyc.id).subquery()
        stmt = (stmt.outerjoin(cnt, cnt.c.fid == FacultyProfile.id).outerjoin(cps, cps.c.fid == FacultyProfile.id))
        cap_col, n_col = func.coalesce(cps.c.c, FacultyProfile.max_capacity), func.coalesce(cnt.c.n, 0)
    if search:
        t = like(search)
        stmt = stmt.where(or_(User.full_name.like(t), User.email.like(t), FacultyProfile.employee_id.like(t)))
    if status:
        stmt = stmt.where(FacultyProfile.approval_status == status)
    if department:
        stmt = stmt.where(FacultyProfile.department == department)
    if available is not None:
        stmt = stmt.where(FacultyProfile.is_available == available)
    if workload == "over":
        stmt = stmt.where(n_col > cap_col, FacultyProfile.approval_status == FAC_APPROVED)
    elif workload == "full":
        stmt = stmt.where(n_col == cap_col, cap_col > 0, FacultyProfile.approval_status == FAC_APPROVED)
    elif workload == "free":
        stmt = stmt.where(n_col < cap_col, FacultyProfile.approval_status == FAC_APPROVED)
    stmt = _sort(stmt, {"name": User.full_name, "department": FacultyProfile.department,
                        "status": FacultyProfile.approval_status, "created": FacultyProfile.created_at,
                        "capacity": cap_col, "assigned": n_col,
                        "workload": n_col * 1000 / func.greatest(cap_col, 1)},
                 sort, FacultyProfile.id)
    r = paginate(db, stmt, page, page_size, unique=True)
    rows = {x["id"]: x for x in wl.faculty_rows(db, cyc)} if cyc else {}
    r["items"] = [{**profile_dict_basic(p), **({"assigned": rows[p.id]["assigned"], "max_capacity": rows[p.id]["max_capacity"],
                                                "remaining": rows[p.id]["remaining"], "overload": rows[p.id]["overload"],
                                                "over_capacity": rows[p.id]["over_capacity"],
                                                "load_ratio": rows[p.id]["load_ratio"]} if p.id in rows else {}),
                   "suggested_capacity": wl.suggested_capacity(db, p.designation)} for p in r["items"]]
    return r


def profile_dict_basic(p: FacultyProfile) -> dict:
    return {"id": p.id, "full_name": p.user.full_name, "email": p.user.email, "employee_id": p.employee_id,
            "department": p.department, "designation": p.designation, "approval_status": p.approval_status,
            "is_active": p.user.is_active, "is_available": p.is_available, "requested_capacity": p.max_capacity,
            "created_at": p.created_at}


def _fac(db: Session, fid: int) -> FacultyProfile:
    p = db.get(FacultyProfile, fid)
    if not p:
        raise HTTPException(404, "Faculty member not found.")
    return p


@router.get("/faculty/{fid}")
def faculty_detail(fid: int, db: Session = Depends(get_db)):
    p = _fac(db, fid)
    d = profile_dict(db, p)
    d["suggested_capacity"] = wl.suggested_capacity(db, p.designation)
    cyc = active_cycle(db, required=False)
    allocs = db.scalars(select(Allocation).where(Allocation.faculty_id == p.id).order_by(Allocation.id.desc())).unique().all()
    d["assignments"] = [{"team_id": a.team_id, "team_name": db.get(Team, a.team_id).name, "status": a.status,
                         "cycle_id": a.cycle_id, "match_tier": a.match_tier, "is_override": a.is_override} for a in allocs]
    d["capacity_limits"] = wl.capacity_limits(db)
    d["capacity_history"] = [{"old": c.old_capacity, "new": c.new_capacity, "reason": c.reason, "assigned": c.assigned_at_change,
                              "changed_by": c.changed_by, "created_at": c.created_at}
                             for c in db.scalars(select(CapacityChange).where(CapacityChange.faculty_id == p.id)
                                                 .order_by(CapacityChange.id.desc())).all()]
    d["requested_capacity"] = p.max_capacity
    return d


@router.patch("/faculty/{fid}")
def update_faculty(fid: int, data: AdminFacultyUpdateIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    p = _fac(db, fid)
    ch = data.model_dump(exclude_unset=True)
    if ch.get("employee_id"):
        emp = ch["employee_id"].strip().upper()
        if db.scalar(select(FacultyProfile.id).where(FacultyProfile.employee_id == emp, FacultyProfile.id != p.id)):
            raise HTTPException(409, "Employee ID already used by another faculty member.")
        p.employee_id = emp
    fsvc.set_faculty_domains(db, p, ch.get("expertise_domain_ids"), ch.get("supported_domain_ids"),
                             ch.get("interest_domain_ids"), ch.get("custom_domain_name"), admin.id)
    if ch.get("full_name"):
        p.user.full_name = ch["full_name"]
    for k in ("department", "designation", "additional_interests", "is_available"):
        if ch.get(k) is not None:
            setattr(p, k, ch[k])
    audit(db, admin.id, "faculty.update", "faculty", p.id, {"fields": list(ch)})
    db.commit()
    return {"ok": True}


@router.post("/faculty/{fid}/approve")
def approve_faculty(fid: int, data: FacultyApproveIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    p = _fac(db, fid)
    res = fsvc.decide_faculty(db, p, admin.id, True, data.remarks, data.capacity)
    return {"approval_status": p.approval_status, **res}


@router.post("/faculty/{fid}/reject")
def reject_faculty(fid: int, data: FacultyDecisionIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    p = _fac(db, fid)
    if db.scalar(select(func.count()).select_from(Allocation).where(Allocation.faculty_id == p.id)):
        raise HTTPException(409, "This faculty member has assigned teams. Reassign them before rejecting.")
    fsvc.decide_faculty(db, p, admin.id, False, data.remarks, None)
    return {"approval_status": p.approval_status}


@router.post("/faculty/{fid}/activate")
def activate_faculty(fid: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    p = _fac(db, fid)
    p.user.is_active = True
    audit(db, admin.id, "faculty.activate", "faculty", p.id)
    db.commit()
    return {"is_active": True}


@router.post("/faculty/{fid}/deactivate")
def deactivate_faculty(fid: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    p = _fac(db, fid)
    p.user.is_active = False
    p.user.token_version += 1
    audit(db, admin.id, "faculty.deactivate", "faculty", p.id)
    db.commit()
    return {"is_active": False, "note": "Existing assignments are kept; no new teams will be assigned."}


@router.put("/faculty/{fid}/capacity")
def set_capacity(fid: int, data: CapacityIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    p = _fac(db, fid)
    cyc = get_cycle(db, data.cycle_id)
    return wl.set_capacity(db, admin.id, p, cyc, data.max_capacity, data.reason, data.confirm_below_assigned,
                           data.expected_capacity)


# ------------------------------------------------------------------ users (password reset issued by admin)
@router.post("/users/{uid}/reset-token")
def issue_reset_token(uid: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Use when e-mail delivery is not configured: the admin hands this one-time token to the user."""
    u = db.get(User, uid)
    if not u or u.role == "admin":
        raise HTTPException(404, "User not found (admin passwords are reset via the CLI script).")
    raw, hashed = new_reset_token()
    db.add(PasswordResetToken(user_id=u.id, token_hash=hashed, expires_at=utcnow() + timedelta(hours=1)))
    audit(db, admin.id, "user.reset_token_issued", "user", u.id)
    db.commit()
    return {"token": raw, "expires_in_minutes": 60, "reset_path": f"/reset-password?token={raw}"}


# ------------------------------------------------------------------ teams
def _team_row(t: Team) -> dict:
    prim = next((td.domain.name for td in t.domains if td.kind == "primary"), None)
    return {"id": t.id, "name": t.name, "department": t.department, "programme": t.programme, "cycle": t.cycle.name,
            "cycle_id": t.cycle_id, "leader": t.leader.full_name, "leader_email": t.leader.email, "members": len(t.members),
            "primary_domain": prim, "project_title": t.proposal.title if t.proposal else "",
            "proposal_status": t.proposal.status if t.proposal else None,
            "eligible": t.proposal.eligible_for_allocation if t.proposal else False,
            "guide": t.allocation.faculty.user.full_name if t.allocation else None,
            "allocation_status": t.allocation.status if t.allocation else None, "created_at": t.created_at}


@router.get("/teams")
def list_teams(page: int = 1, page_size: int = 20, search: str | None = None, cycle_id: int | None = None,
               department: str | None = None, proposal_status: str | None = None, allocated: bool | None = None,
               sort: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Team).join(Proposal, Proposal.team_id == Team.id).join(User, User.id == Team.leader_user_id)
    if cycle_id is None:
        c = active_cycle(db, required=False)
        cycle_id = c.id if c else None
    if cycle_id:
        stmt = stmt.where(Team.cycle_id == cycle_id)
    if search:
        t = like(search)
        stmt = stmt.where(or_(Team.name.like(t), User.full_name.like(t), User.email.like(t), Proposal.title.like(t),
                              Team.id.in_(select(TeamMember.team_id).where(or_(
                                  TeamMember.registration_number.like(t), TeamMember.full_name.like(t),
                                  TeamMember.email.like(t))))))
    if department:
        stmt = stmt.where(Team.department == department)
    if proposal_status:
        stmt = stmt.where(Proposal.status == proposal_status)
    if allocated is not None:
        has = select(Allocation.team_id).where(Allocation.cycle_id == Team.cycle_id)
        stmt = stmt.where(Team.id.in_(has) if allocated else Team.id.not_in(has))
    stmt = _sort(stmt, {"name": Team.name, "department": Team.department, "created": Team.created_at,
                        "status": Proposal.status, "title": Proposal.title}, sort, Team.id)
    r = paginate(db, stmt, page, page_size, unique=True)
    r["items"] = [_team_row(t) for t in r["items"]]
    return r


def _team(db: Session, tid: int) -> Team:
    t = db.get(Team, tid)
    if not t:
        raise HTTPException(404, "Team not found.")
    return t


@router.get("/teams/{tid}")
def team_detail(tid: int, db: Session = Depends(get_db)):
    return tsvc.serialize_team(_team(db, tid))


@router.patch("/teams/{tid}")
def admin_update_team(tid: int, data: TeamUpdateIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    t = _team(db, tid)
    tsvc.update_team(db, t, data, admin.id, is_admin=True)
    db.commit()
    return tsvc.serialize_team(_team(db, tid))


@router.post("/teams/{tid}/members", status_code=201)
def admin_add_member(tid: int, data: MemberIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    m = tsvc.add_member(db, _team(db, tid), data, admin.id, is_admin=True)
    db.commit()
    return tsvc.serialize_member(m)


@router.put("/teams/{tid}/members/{mid}")
def admin_update_member(tid: int, mid: int, data: MemberUpdateIn, admin: User = Depends(require_admin),
                        db: Session = Depends(get_db)):
    t, m = _team(db, tid), db.get(TeamMember, mid)
    if not m or m.team_id != t.id:
        raise HTTPException(404, "Member not found in this team.")
    tsvc.update_member(db, t, m, data, admin.id, is_admin=True)
    db.commit()
    return tsvc.serialize_member(m)


@router.delete("/teams/{tid}/members/{mid}", status_code=204)
def admin_remove_member(tid: int, mid: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    t, m = _team(db, tid), db.get(TeamMember, mid)
    if not m or m.team_id != t.id:
        raise HTTPException(404, "Member not found in this team.")
    tsvc.remove_member(db, t, m, admin.id, is_admin=True)
    db.commit()


@router.get("/change-requests")
def change_requests(status: str | None = "pending", page: int = 1, page_size: int = 20, db: Session = Depends(get_db)):
    stmt = select(TeamChangeRequest).order_by(TeamChangeRequest.id.desc())
    if status:
        stmt = stmt.where(TeamChangeRequest.status == status)
    r = paginate(db, stmt, page, page_size)
    r["items"] = [{"id": c.id, "team_id": c.team_id, "team_name": db.get(Team, c.team_id).name, "description": c.description,
                   "status": c.status, "admin_remarks": c.admin_remarks, "created_at": c.created_at} for c in r["items"]]
    return r


@router.post("/change-requests/{cid}/resolve")
def resolve_change_request(cid: int, data: ChangeRequestResolve, admin: User = Depends(require_admin),
                           db: Session = Depends(get_db)):
    c = db.get(TeamChangeRequest, cid)
    if not c or c.status != "pending":
        raise HTTPException(404, "Pending change request not found.")
    c.status = "approved" if data.action == "approve" else "rejected"
    c.admin_remarks, c.resolved_by, c.resolved_at = data.remarks, admin.id, utcnow()
    team = db.get(Team, c.team_id)
    notify(db, team.leader_user_id, f"Change request {c.status}",
           f"Your request was {c.status}. {data.remarks} " + ("The administrator will apply the change." if c.status == "approved" else ""),
           "change_request")
    audit(db, admin.id, f"team.change_request_{c.status}", "team", c.team_id, {"request_id": c.id})
    db.commit()
    return {"status": c.status}


# ------------------------------------------------------------------ proposals
@router.get("/proposals")
def list_proposals(page: int = 1, page_size: int = 20, search: str | None = None, status: str | None = None,
                   cycle_id: int | None = None, sort: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Proposal).join(Team, Team.id == Proposal.team_id).where(Proposal.status != "draft")
    if cycle_id is None:
        c = active_cycle(db, required=False)
        cycle_id = c.id if c else None
    if cycle_id:
        stmt = stmt.where(Team.cycle_id == cycle_id)
    if status:
        stmt = stmt.where(Proposal.status == status)
    if search:
        t = like(search)
        stmt = stmt.where(or_(Proposal.title.like(t), Team.name.like(t)))
    stmt = _sort(stmt, {"title": Proposal.title, "status": Proposal.status, "submitted": Proposal.submitted_at,
                        "team": Team.name}, sort, Proposal.id)
    r = paginate(db, stmt, page, page_size, unique=True)
    items = []
    for p in r["items"]:
        t = db.get(Team, p.team_id)
        items.append({"id": p.id, "team_id": t.id, "team_name": t.name, "title": p.title, "status": p.status,
                      "eligible": p.eligible_for_allocation, "submitted_at": p.submitted_at,
                      "primary_domain": next((td.domain.name for td in t.domains if td.kind == "primary"), None)})
    r["items"] = items
    return r


@router.get("/proposals/{pid}")
def proposal_detail(pid: int, db: Session = Depends(get_db)):
    p = db.get(Proposal, pid)
    if not p:
        raise HTTPException(404, "Proposal not found.")
    t = db.get(Team, p.team_id)
    return {"team": tsvc.serialize_team(t)}


@router.post("/proposals/{pid}/review")
def review(pid: int, data: ReviewIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    p = db.get(Proposal, pid)
    if not p:
        raise HTTPException(404, "Proposal not found.")
    psvc.review_proposal(db, p, admin.id, data)
    return {"status": p.status, "eligible": p.eligible_for_allocation}


# ------------------------------------------------------------------ domains
@router.get("/domains")
def admin_domains(page: int = 1, page_size: int = 100, search: str | None = None, active: bool | None = None,
                  custom_status: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Domain)
    if search:
        stmt = stmt.where(Domain.name.like(like(search)))
    if active is not None:
        stmt = stmt.where(Domain.is_active == active)
    if custom_status:
        stmt = stmt.where(Domain.custom_status == custom_status)
    r = paginate(db, stmt.order_by(Domain.is_other, Domain.name), page, page_size)
    use_t = dict(db.execute(select(TeamDomain.domain_id, func.count()).group_by(TeamDomain.domain_id)).all())
    from ..models import FacultyDomain
    use_f = dict(db.execute(select(FacultyDomain.domain_id, func.count()).group_by(FacultyDomain.domain_id)).all())
    r["items"] = [{**DomainOut.model_validate(d).model_dump(), "team_usage": use_t.get(d.id, 0),
                   "faculty_usage": use_f.get(d.id, 0)} for d in r["items"]]
    return r


def _check_parent(db: Session, dom_id: int | None, parent_id: int | None):
    if parent_id is None:
        return
    if dom_id is not None and parent_id == dom_id:
        raise HTTPException(422, "A domain cannot be its own parent.")
    par = db.get(Domain, parent_id)
    if not par:
        raise HTTPException(422, "Parent domain does not exist.")
    seen = {dom_id}
    while par is not None:                       # prevent cycles
        if par.id in seen:
            raise HTTPException(422, "That parent would create a loop in the domain hierarchy.")
        seen.add(par.id)
        par = db.get(Domain, par.parent_id) if par.parent_id else None


@router.post("/domains", status_code=201, response_model=DomainOut)
def create_domain(data: DomainIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    name = " ".join(data.name.split())
    if db.scalar(select(Domain.id).where(func.lower(Domain.name) == name.lower())):
        raise HTTPException(409, "A domain with this name already exists.")
    _check_parent(db, None, data.parent_id)
    d = Domain(name=name, description=data.description, parent_id=data.parent_id, created_by_user_id=admin.id)
    db.add(d)
    db.flush()
    audit(db, admin.id, "domain.create", "domain", d.id, {"name": name})
    db.commit()
    return d


@router.patch("/domains/{did}", response_model=DomainOut)
def update_domain(did: int, data: DomainUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    d = db.get(Domain, did)
    if not d:
        raise HTTPException(404, "Domain not found.")
    ch = data.model_dump(exclude_unset=True)
    if d.is_other and ("name" in ch or ch.get("is_active") is False):
        raise HTTPException(409, "The 'Other' entry is required and cannot be renamed or deactivated.")
    if ch.get("name"):
        name = " ".join(ch["name"].split())
        if db.scalar(select(Domain.id).where(func.lower(Domain.name) == name.lower(), Domain.id != d.id)):
            raise HTTPException(409, "A domain with this name already exists.")
        d.name = name
    if ch.get("description") is not None:
        d.description = ch["description"]
    if data.clear_parent:
        d.parent_id = None
    elif ch.get("parent_id") is not None:
        _check_parent(db, d.id, ch["parent_id"])
        d.parent_id = ch["parent_id"]
    if ch.get("is_active") is not None:
        d.is_active = ch["is_active"]       # deactivating keeps every existing reference intact
    audit(db, admin.id, "domain.update", "domain", d.id, {k: v for k, v in ch.items()})
    db.commit()
    return d


@router.post("/domains/{did}/review-custom", response_model=DomainOut)
def review_custom(did: int, data: CustomDomainReview, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    d = db.get(Domain, did)
    if not d or not d.is_custom:
        raise HTTPException(404, "Custom domain not found.")
    if data.action == "approve":
        d.custom_status, d.is_active = "approved", True
    elif data.action == "reject":
        d.custom_status, d.is_active = "rejected", False
    else:
        if not data.map_to_domain_id:
            raise HTTPException(422, "map_to_domain_id is required to map a custom domain.")
        _check_parent(db, d.id, data.map_to_domain_id)
        d.parent_id, d.custom_status = data.map_to_domain_id, "approved"   # matching then uses the parent relation
    audit(db, admin.id, f"domain.custom_{data.action}", "domain", d.id)
    db.commit()
    return d


# ------------------------------------------------------------------ cycles
def _cycle_out(c: AllocationCycle) -> dict:
    return {"id": c.id, "name": c.name, "academic_year": c.academic_year, "status": c.status, "is_active": c.is_active,
            "start_date": c.start_date, "end_date": c.end_date, "registration_deadline": c.registration_deadline,
            "proposal_deadline": c.proposal_deadline, "finalised_at": c.finalised_at}


@router.get("/cycles")
def list_cycles(db: Session = Depends(get_db)):
    return [_cycle_out(c) for c in db.scalars(select(AllocationCycle).order_by(AllocationCycle.id.desc()))]


@router.post("/cycles", status_code=201)
def create_cycle(data: CycleIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.scalar(select(AllocationCycle.id).where(AllocationCycle.name == data.name)):
        raise HTTPException(409, "A cycle with this name already exists.")
    c = AllocationCycle(**data.model_dump(), status=CYCLE_PLANNED)
    db.add(c)
    db.flush()
    audit(db, admin.id, "cycle.create", "cycle", c.id, {"name": c.name})
    db.commit()
    return _cycle_out(c)


@router.patch("/cycles/{cid}")
def update_cycle(cid: int, data: CycleUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    c = db.get(AllocationCycle, cid)
    if not c:
        raise HTTPException(404, "Cycle not found.")
    ch = data.model_dump(exclude_unset=True)
    if ch.get("status") == "archived" and c.is_active:
        raise HTTPException(409, "Activate a different cycle before archiving this one.")
    if "status" in ch and c.status == CYCLE_FINALISED and ch["status"] == "planned":
        raise HTTPException(409, "A finalised cycle cannot be reopened.")
    for k, v in ch.items():
        setattr(c, k, v)
    audit(db, admin.id, "cycle.update", "cycle", c.id, {k: str(v) for k, v in ch.items()})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A cycle with this name already exists.")
    return _cycle_out(c)


@router.post("/cycles/{cid}/activate")
def activate_cycle(cid: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Explicit admin choice. The previous cycle is untouched except it stops being 'current'."""
    c = db.execute(select(AllocationCycle).where(AllocationCycle.id == cid).with_for_update()).scalar_one_or_none()
    if not c:
        raise HTTPException(404, "Cycle not found.")
    if c.status == "archived":
        raise HTTPException(409, "Archived cycles cannot be activated.")
    prev = db.scalar(select(AllocationCycle).where(AllocationCycle.active_marker == 1))
    if prev and prev.id != c.id:
        prev.active_marker = None
        if prev.status == CYCLE_ACTIVE:
            prev.status = CYCLE_PLANNED
        db.flush()
    c.active_marker = 1
    if c.status == CYCLE_PLANNED:
        c.status = CYCLE_ACTIVE
    audit(db, admin.id, "cycle.activate", "cycle", c.id, {"previous": prev.id if prev else None})
    db.commit()
    return _cycle_out(c)


# ------------------------------------------------------------------ settings / audit / history
@router.get("/settings")
def get_settings_(db: Session = Depends(get_db)):
    vals = all_settings(db)
    return {"values": vals, "descriptions": {k: v[1] for k, v in DEFAULT_SETTINGS.items()}}


@router.put("/settings")
def put_settings(data: SettingsIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    bad = [k for k in data.values if k not in DEFAULT_SETTINGS]
    if bad:
        raise HTTPException(422, f"Unknown setting(s): {', '.join(bad)}")
    merged = {**all_settings(db), **data.values}
    for key in ("min_team_size", "max_team_size", "min_compatibility_score", "default_faculty_capacity",
                "min_faculty_capacity", "max_faculty_capacity"):
        try:
            merged[key] = data.values.get(key, merged[key])
            merged[key] = int(merged[key])
        except (TypeError, ValueError):
            raise HTTPException(422, f"{key} must be a whole number.")
    if not (1 <= merged["min_team_size"] <= merged["max_team_size"] <= 50):
        raise HTTPException(422, "Team sizes must satisfy 1 <= minimum <= maximum <= 50.")
    if merged["min_compatibility_score"] < 0 or merged["default_faculty_capacity"] < 0:
        raise HTTPException(422, "Values cannot be negative.")
    if not (0 <= merged["min_faculty_capacity"] <= merged["max_faculty_capacity"] <= 1000):
        raise HTTPException(422, "Capacity limits must satisfy 0 <= minimum <= maximum <= 1000.")
    for key in ("allow_cross_department", "allow_cross_programme", "restrict_faculty_to_team_department"):
        if not isinstance(merged[key], bool):
            raise HTTPException(422, f"{key} must be true or false.")
    if not isinstance(merged["designation_capacity_defaults"], dict) or not all(
            isinstance(v, int) and 0 <= v <= 100 for v in merged["designation_capacity_defaults"].values()):
        raise HTTPException(422, "designation_capacity_defaults must map designation names to whole numbers 0-100.")
    if not isinstance(merged["allowed_email_domains"], str):
        raise HTTPException(422, "allowed_email_domains must be text.")
    for k in data.values:
        row = db.get(SystemSetting, k)
        if row is None:
            db.add(SystemSetting(key=k, value=merged[k], description=DEFAULT_SETTINGS[k][1]))
        else:
            row.value = merged[k]
    audit(db, admin.id, "settings.update", "settings", None, {k: merged[k] for k in data.values})
    db.commit()
    return get_settings_(db)


@router.get("/audit-logs")
def audit_logs(page: int = 1, page_size: int = 25, action: str | None = None, entity_type: str | None = None,
               search: str | None = None, db: Session = Depends(get_db)):
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    if action:
        stmt = stmt.where(AuditLog.action.like(like(action)))
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if search:
        stmt = stmt.where(AuditLog.actor_user_id.in_(select(User.id).where(or_(User.full_name.like(like(search)),
                                                                                User.email.like(like(search))))))
    r = paginate(db, stmt, page, page_size, unique=True)
    r["items"] = [{"id": a.id, "action": a.action, "entity_type": a.entity_type, "entity_id": a.entity_id,
                   "details": a.details, "actor": a.actor.full_name if a.actor else None, "created_at": a.created_at}
                  for a in r["items"]]
    return r


@router.get("/allocation-history")
def allocation_history(page: int = 1, page_size: int = 25, cycle_id: int | None = None, team_id: int | None = None,
                       action: str | None = None, db: Session = Depends(get_db)):
    stmt = select(AllocationHistory).order_by(AllocationHistory.id.desc())
    if cycle_id:
        stmt = stmt.where(AllocationHistory.cycle_id == cycle_id)
    if team_id:
        stmt = stmt.where(AllocationHistory.team_id == team_id)
    if action:
        stmt = stmt.where(AllocationHistory.action == action)
    r = paginate(db, stmt, page, page_size)
    fname = lambda fid: db.get(FacultyProfile, fid).user.full_name if fid else None
    r["items"] = [{"id": h.id, "cycle": db.get(AllocationCycle, h.cycle_id).name, "team_id": h.team_id,
                   "team": db.get(Team, h.team_id).name, "action": h.action, "old_faculty": fname(h.old_faculty_id),
                   "new_faculty": fname(h.new_faculty_id), "reason": h.reason, "is_override": h.is_override,
                   "domain_violation": h.domain_violation, "capacity_violation": h.capacity_violation,
                   "projected_load": h.projected_load, "capacity_at_time": h.capacity_at_time, "details": h.details,
                   "performed_by": db.get(User, h.performed_by).full_name, "created_at": h.created_at} for h in r["items"]]
    return r
