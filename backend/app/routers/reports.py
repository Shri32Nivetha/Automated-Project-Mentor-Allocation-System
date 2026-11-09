"""Admin reports (JSON preview + CSV export) built from live database data."""
import csv
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_admin
from ..models import (Allocation, AllocationHistory, Domain, FacultyProfile, Proposal, Team, TeamDomain, User)
from ..services import team_reports as tr
from ..services import workload as wl
from ..services.common import get_cycle
from . import allocation as alloc_router

router = APIRouter(prefix="/admin/reports", tags=["reports"], dependencies=[Depends(require_admin)])


def _safe(v):
    """Neutralise spreadsheet formula injection and format values for CSV."""
    if v is None:
        return ""
    s = v.isoformat() if hasattr(v, "isoformat") else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def r_registrations(db, cyc):
    rows = []
    for t in db.scalars(select(Team).where(Team.cycle_id == cyc.id).order_by(Team.id)).unique():
        for m in t.members:
            rows.append([t.id, t.name, t.department, t.programme, m.full_name, m.registration_number, m.email,
                         "Yes" if m.is_leader else "No", t.created_at])
    return ["Team ID", "Team", "Department", "Programme", "Member", "Registration No.", "Email", "Leader", "Registered at"], rows


def r_domains(db, cyc):
    q = (select(Domain.name, func.count()).join(TeamDomain, TeamDomain.domain_id == Domain.id)
         .join(Team, Team.id == TeamDomain.team_id).where(Team.cycle_id == cyc.id, TeamDomain.kind == "primary")
         .group_by(Domain.name).order_by(func.count().desc(), Domain.name))
    return ["Primary domain", "Teams"], [list(r) for r in db.execute(q)]


def r_proposals(db, cyc):
    q = (select(Proposal.status, func.count()).join(Team, Team.id == Proposal.team_id).where(Team.cycle_id == cyc.id)
         .group_by(Proposal.status).order_by(Proposal.status))
    return ["Proposal status", "Teams"], [list(r) for r in db.execute(q)]


def r_workload(db, cyc):
    rows = wl.faculty_rows(db, cyc, only_approved=True)
    return (["Faculty", "Employee ID", "Department", "Designation", "Assigned", "Max capacity", "Remaining", "Load ratio",
             "Eligible for new teams", "Reason"],
            [[r["name"], r["employee_id"], r["department"], r["designation"], r["assigned"], r["max_capacity"],
              r["remaining"], r["load_ratio"], "Yes" if r["eligible_for_allocation"] else "No", r["ineligible_reason"]]
             for r in rows])


def r_allocations(db, cyc):
    rows = []
    for a in db.scalars(select(Allocation).where(Allocation.cycle_id == cyc.id).order_by(Allocation.id)).unique():
        t = db.get(Team, a.team_id)
        rows.append([t.name, t.proposal.title, a.faculty.user.full_name, a.faculty.department, a.status, a.method, a.score,
                     a.created_at])
    return ["Team", "Project title", "Guide", "Guide department", "Status", "Method", "Score", "Assigned at"], rows


def r_unallocated(db, cyc):
    data = alloc_router.unallocated(cyc.id, db)
    return ["Team", "Project title", "Proposal status", "Reason"], [[d["team_name"], d["project_title"], d["proposal_status"],
                                                                     d["reason"]] for d in data]


def r_history(db, cyc):
    rows = []
    fn = lambda i: db.get(FacultyProfile, i).user.full_name if i else ""
    for h in db.scalars(select(AllocationHistory).where(AllocationHistory.cycle_id == cyc.id).order_by(AllocationHistory.id)):
        rows.append([h.created_at, db.get(Team, h.team_id).name, h.action, fn(h.old_faculty_id), fn(h.new_faculty_id),
                     h.reason, db.get(User, h.performed_by).full_name])
    return ["When", "Team", "Action", "Old guide", "New guide", "Reason", "By"], rows


REPORTS = {"registrations": r_registrations, "teams-by-domain": r_domains, "proposal-status": r_proposals,
           "faculty-workload": r_workload, "faculty-capacity": r_workload, "allocations": r_allocations,
           "unallocated": r_unallocated, "allocation-history": r_history}


@router.get("/team-composition")
def team_composition_report(cycle_id: int | None = None, format: str = "json", db: Session = Depends(get_db)):
    """Teams with their lead and members (JSON for the on-screen view, PDF or XLSX for download)."""
    cyc = get_cycle(db, cycle_id)
    data = tr.team_composition(db, cyc)
    return tr.respond(format, data, cyc, "team_composition_report", tr.composition_pdf, tr.composition_xlsx)


@router.get("/team-mentor")
def team_mentor_report(cycle_id: int | None = None, format: str = "json", db: Session = Depends(get_db)):
    """One row per team with its assigned mentor (guide) or 'Not Assigned'."""
    cyc = get_cycle(db, cycle_id)
    data = tr.team_mentor(db, cyc)
    return tr.respond(format, data, cyc, "team_mentor_allocation_report", tr.mentor_pdf, tr.mentor_xlsx)


@router.get("/{name}")
def report(name: str, cycle_id: int | None = None, format: str = "json", db: Session = Depends(get_db)):
    fn = REPORTS.get(name)
    if fn is None:
        raise HTTPException(404, "Unknown report.")
    cyc = get_cycle(db, cycle_id)
    cols, rows = fn(db, cyc)
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        for r in rows:
            w.writerow([_safe(c) for c in r])
        data = "\ufeff" + buf.getvalue()  # BOM so Excel reads UTF-8 (accents, non-Latin names) correctly
        return StreamingResponse(iter([data]), media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="{name}_{cyc.id}.csv"'})
    return {"cycle": {"id": cyc.id, "name": cyc.name}, "columns": cols,
            "rows": [[(c.isoformat() if hasattr(c, "isoformat") else c) for c in r] for r in rows]}
