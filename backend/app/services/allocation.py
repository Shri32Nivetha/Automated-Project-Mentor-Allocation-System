"""Guide allocation service: global optimisation, preview/commit, administrator override, finalisation.

POLICY (details in optimizer.py and the README)
  Mandatory (never relaxed by the optimiser): approved faculty, active account, marked available, capacity > 0,
  department restriction (when enabled), and a COMPATIBLE DOMAIN (primary > additional > related). A team for which
  no such mentor exists is reported as "requires administrative resolution"; it is never given an incompatible mentor.
  Capacity is a *nominal* limit: when demand exceeds it, the optimiser spreads the unavoidable overload (worst first).
  Administrators can override domain compatibility and/or nominal capacity manually, with a recorded reason.
No machine learning is used; the optimiser is an exact constraint solver (OR-Tools CP-SAT).
"""
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import utcnow
from ..models import (A_ALLOCATED, A_FINALISED, CYCLE_ACTIVE, CYCLE_FINALISED, FAC_APPROVED, P_ALLOCATED, P_APPROVED,
                      P_FINALISED, Allocation, AllocationCycle, AllocationHistory, AllocationPreview,
                      FacultyCycleCapacity, FacultyProfile, Domain, Proposal, Team, User)
from . import optimizer, workload
from .common import audit, get_setting, notify
from .faculty import serialize_faculty_domains
from .matching import (DEPT_BONUS, INTEREST_CAP, TIER_NAMES, W_INTEREST, W_PRIMARY, FacView, TeamView,  # noqa: F401
                       match_pair, score_pair)


# ---------------------------------------------------------------- database -> pure views
def load_parents(db: Session):
    rows = db.execute(select(Domain.id, Domain.name, Domain.parent_id)).all()
    return {r[0]: r[2] for r in rows}, {r[0]: r[1] for r in rows}


def restrict_department(db: Session) -> bool:
    return bool(get_setting(db, "restrict_faculty_to_team_department"))


def fac_views(db: Session, cycle_id: int, only_approved=True, exclude_team_ids=()) -> list[FacView]:
    """Faculty with capacity and CURRENT workload. Allocations of ``exclude_team_ids`` are not counted, which is how
    teams that are being re-optimised avoid being counted twice (once as existing load, once as a new assignment)."""
    caps = workload.capacity_map(db, cycle_id)
    counts = workload.assigned_counts(db, cycle_id, exclude_team_ids)
    stmt = select(FacultyProfile).order_by(FacultyProfile.id)
    if only_approved:
        stmt = stmt.where(FacultyProfile.approval_status == FAC_APPROVED)
    out = []
    for f in db.scalars(stmt).unique():
        cap, n = caps.get(f.id, f.max_capacity), counts.get(f.id, 0)
        problem = None
        if f.approval_status != FAC_APPROVED:
            problem = f"registration is {f.approval_status}"
        elif not f.user.is_active:
            problem = "account is deactivated"
        elif not f.is_available:
            problem = "marked unavailable"
        fv = FacView(f.id, f.user.full_name, f.department, cap, n, problem)
        for fd in f.domains:
            getattr(fv, fd.kind).add(fd.domain_id)
        out.append(fv)
    return out


def team_view(t: Team) -> TeamView:
    prim = next((td.domain_id for td in t.domains if td.kind == "primary"), None)
    return TeamView(t.id, t.name, t.proposal.title if t.proposal else "", t.department, prim,
                    {td.domain_id for td in t.domains if td.kind == "interest"})


def _team_domain_info(t: Team) -> dict:
    return {"team_domain": next((td.domain.name for td in t.domains if td.kind == "primary"), None),
            "team_interests": sorted(td.domain.name for td in t.domains if td.kind == "interest"),
            "team_department": t.department}


# ---------------------------------------------------------------- explanations for teams without a mentor
def _unresolved(team: TeamView, facs: list[FacView], parents: dict, names: dict, restrict: bool) -> dict:
    usable = [f for f in facs if f.status_problem is None and f.capacity > 0]
    if not usable:
        return {"code": "no_eligible_faculty",
                "reason": "No faculty member is currently eligible (approved, active, available and with capacity above zero).",
                "suggestions": []}
    scored = [(f, match_pair(team, f, parents, names, restrict)) for f in usable]
    if restrict and all(s["dept_blocked"] for _, s in scored):
        return {"code": "department_restriction",
                "reason": f"No eligible faculty from the '{team.department}' department (department restriction is on).",
                "suggestions": []}
    pool = [(f, s) for f, s in scored if not s["dept_blocked"]]
    doms = [names.get(team.primary, "its primary domain")] + [names.get(i, str(i)) for i in sorted(team.interests)]
    # who could the administrator consider? best fit first, then least busy. These are NOT compatible: override needed.
    pool.sort(key=lambda fs: (-fs[1]["domain_score"], fs[0].assigned / fs[0].capacity, fs[0].id))
    suggestions = [{"faculty_id": f.id, "name": f.name, "assigned": f.assigned, "capacity": f.capacity,
                    "domain_score": s["domain_score"]} for f, s in pool[:3]]
    return {"code": "no_compatible_domain",
            "reason": ("No eligible mentor matches the team's primary domain, any of its additional domains, or a "
                       f"related (parent/child) domain: {', '.join(doms)}. Administrative resolution is required "
                       "(manual assignment with an override reason)."),
            "suggestions": suggestions}


# ---------------------------------------------------------------- the optimisation run (pure)
def run_optimizer(teams: list[TeamView], facs: list[FacView], parents: dict, names: dict, restrict: bool,
                  time_limit: float = 30.0, workers: int = 1) -> dict:
    """Pure function: mandatory eligibility + domain compatibility -> CP-SAT -> explainable result."""
    teams = sorted(teams, key=lambda t: t.id)
    facs = sorted(facs, key=lambda f: f.id)
    fby = {f.id: f for f in facs}
    matches, edges = {}, {}
    cands: dict[int, list[int]] = defaultdict(list)
    for t in teams:
        for f in facs:
            if f.status_problem is not None or f.capacity <= 0:
                continue
            mt = match_pair(t, f, parents, names, restrict)
            if mt["compatible"]:
                matches[(t.id, f.id)] = mt
                edges[(t.id, f.id)] = optimizer.Edge(mt["tier"], mt["exact_count"], mt["related_count"],
                                                     int(round(mt["total"] * 100)))
                cands[t.id].append(f.id)
    unassigned = []
    for t in teams:
        if not cands[t.id]:
            unassigned.append({"team_id": t.id, **_unresolved(t, facs, parents, names, restrict)})

    res = optimizer.solve([t.id for t in teams if cands[t.id]], {f.id: f.assigned for f in facs},
                          {f.id: f.capacity for f in facs if f.capacity > 0}, edges, time_limit, workers)

    projected = {f.id: f.assigned for f in facs}
    for fid in res.assignment.values():
        projected[fid] += 1
    over = lambda f_id, load: max(0, load - fby[f_id].capacity)  # noqa: E731

    tby = {t.id: t for t in teams}
    assignments = []
    for tid in sorted(res.assignment):
        fid = res.assignment[tid]
        mt, f = matches[(tid, fid)], fby[fid]
        # why this mentor and not the best-tier one?
        best_tier = min(matches[(tid, c)]["tier"] for c in cands[tid])
        alt = None
        if mt["tier"] > best_tier:
            better = [c for c in cands[tid] if matches[(tid, c)]["tier"] == best_tier]
            desc = ", ".join(f"{fby[c].name} ({projected[c]}/{fby[c].capacity})" for c in better[:4])
            if all(projected[c] >= fby[c].capacity for c in better):
                alt = (f"{TIER_NAMES[best_tier].capitalize()}-domain mentor(s) {desc} are at or over capacity in the proposed "
                       f"plan, so a {mt['tier_name']}-domain mentor was selected to avoid extra overload.")
            else:
                alt = (f"{TIER_NAMES[best_tier].capitalize()}-domain mentor(s) exist ({desc}), but using them for this team "
                       f"would have worsened overload elsewhere in the cycle, so a {mt['tier_name']}-domain mentor was selected.")
        else:
            same = [c for c in cands[tid] if matches[(tid, c)]["tier"] == mt["tier"]]
            top = max(same, key=lambda c: (matches[(tid, c)]["total"], -c))
            if top != fid and matches[(tid, top)]["total"] > mt["total"]:
                alt = (f"{fby[top].name} fits slightly better on domain score ({matches[(tid, top)]['total']} vs {mt['total']}) "
                       f"but workload balancing took precedence (projected {projected[top]}/{fby[top].capacity}).")
        assignments.append({
            "team_id": tid, "faculty_id": fid, "score": mt["total"], "domain_score": mt["domain_score"],
            "tier": mt["tier_name"], "tier_rank": mt["tier"], "matched_domains": mt["matched"],
            "explanation": "; ".join(mt["notes"]), "alternative_reason": alt,
            "faculty_assigned_before": f.assigned, "faculty_current": f.assigned, "faculty_capacity": f.capacity,
            "faculty_projected": projected[fid], "overload": over(fid, projected[fid]),
            "remaining_after": max(0, f.capacity - projected[fid]),
            "overload_warning": (f"{f.name} will carry {projected[fid]} teams against a capacity of {f.capacity} "
                                 f"(+{over(fid, projected[fid])})") if projected[fid] > f.capacity else None,
            "compatible_alternatives": len(cands[tid]) - 1})

    projection = []
    for f in facs:
        cur_over, new_over = over(f.id, f.assigned), over(f.id, projected[f.id])
        projection.append({"faculty_id": f.id, "name": f.name, "department": f.department, "capacity": f.capacity,
                           "current": f.assigned, "projected": projected[f.id], "added": projected[f.id] - f.assigned,
                           "overload": new_over, "added_overload": new_over - cur_over,
                           "utilisation": round(projected[f.id] / f.capacity, 3) if f.capacity > 0 else None,
                           "eligible": f.status_problem is None and f.capacity > 0, "problem": f.status_problem})
    tiers = defaultdict(int)
    for a in assignments:
        tiers[a["tier"]] += 1
    summary = {"teams_considered": len(teams), "teams_assigned": len(assignments),
               "teams_requiring_resolution": len(unassigned),
               "tier_counts": {"primary": tiers["primary"], "additional": tiers["additional"], "related": tiers["related"]},
               "total_overload": sum(p["overload"] for p in projection),
               "max_overload": max((p["overload"] for p in projection), default=0),
               "new_overload": sum(max(0, p["added_overload"]) for p in projection),
               "overloaded_faculty": sum(1 for p in projection if p["overload"] > 0)}
    solver = {"engine": "OR-Tools CP-SAT (lexicographic)", "proved_optimal": res.proved_optimal, "seconds": res.seconds,
              "stages": res.stages}
    return {"assignments": assignments, "unassigned": unassigned, "faculty_projection": projection,
            "summary_run": summary, "solver": solver}


# ---------------------------------------------------------------- preview
def _require_open(cycle: AllocationCycle, for_auto: bool):
    if cycle.status == "archived":
        raise HTTPException(409, "This cycle is archived and cannot be changed.")
    if for_auto and cycle.status != CYCLE_ACTIVE:
        raise HTTPException(409, f"Automatic allocation requires an active cycle (this cycle is '{cycle.status}'). "
                                 "Finalised cycles are preserved; use manual reassignment with a reason.")


def _reoptimisable(db: Session, cycle_id: int, include_manual: bool) -> list[Team]:
    """Teams that already have a NOT finalised allocation and may be re-decided. Manual ones only on explicit request."""
    stmt = (select(Team).join(Allocation, Allocation.team_id == Team.id).join(Proposal, Proposal.team_id == Team.id)
            .where(Team.cycle_id == cycle_id, Allocation.status == A_ALLOCATED, Proposal.status == P_ALLOCATED,
                   Proposal.eligible_for_allocation == True).order_by(Team.id))  # noqa: E712
    if not include_manual:
        stmt = stmt.where(Allocation.method == "auto")
    return list(db.scalars(stmt).unique())


def build_preview(db: Session, admin: User, cycle: AllocationCycle, reoptimize: bool = False,
                  include_manual: bool = False) -> AllocationPreview:
    """Compute the proposal. Nothing is allocated; only an AllocationPreview row is stored."""
    _require_open(cycle, True)
    if include_manual and not reoptimize:
        raise HTTPException(422, "Including manual assignments only makes sense together with re-optimisation.")
    cfg = get_settings()
    _, unalloc = workload.team_pool(db, cycle.id)
    parents, names = load_parents(db)
    restrict = restrict_department(db)

    resolve_teams = _reoptimisable(db, cycle.id, include_manual) if reoptimize else []
    # existing allocations of teams that have no compatible mentor stay as they are (never silently dropped)
    full = fac_views(db, cycle.id)
    usable = [f for f in full if f.status_problem is None and f.capacity > 0]
    kept, solve_existing = [], []
    for t in resolve_teams:
        tv = team_view(t)
        (solve_existing if any(match_pair(tv, f, parents, names, restrict)["compatible"] for f in usable) else kept).append(t)
    existing_fac = {t.id: t.allocation.faculty_id for t in resolve_teams}
    existing_method = {t.id: t.allocation.method for t in resolve_teams}
    pool = list(unalloc) + solve_existing
    facs = fac_views(db, cycle.id, exclude_team_ids=[t.id for t in solve_existing])

    try:
        out = run_optimizer([team_view(t) for t in pool], facs, parents, names, restrict,
                            cfg.allocation_solver_time_limit_seconds, cfg.allocation_solver_workers)
    except optimizer.SolverError as e:
        audit(db, admin.id, "allocation.preview_failed", "cycle", cycle.id, {"code": e.code})
        db.commit()
        status = 504 if e.code == "timeout" else 503
        raise HTTPException(status, {"code": f"solver_{e.code}", "message": e.message +
                                     " No allocation was changed. Try again, or assign the remaining teams manually."})

    fname = {f.id: f.name for f in full}
    tmap = {t.id: t for t in pool + kept}
    for a in out["assignments"]:
        t = tmap[a["team_id"]]
        cur = existing_fac.get(t.id)
        a.update(team_name=t.name, project_title=t.proposal.title, faculty_name=fname[a["faculty_id"]],
                 current_faculty_id=cur, current_faculty_name=fname.get(cur) if cur else None,
                 change=("new" if cur is None else "unchanged" if cur == a["faculty_id"] else "reassign"),
                 **_team_domain_info(t))
    for u in out["unassigned"]:
        t = tmap[u["team_id"]]
        u.update(team_name=t.name, project_title=t.proposal.title, **_team_domain_info(t))
    for t in kept:
        reason = _unresolved(team_view(t), full, parents, names, restrict)
        out["unassigned"].append({"team_id": t.id, **reason, "team_name": t.name, "project_title": t.proposal.title,
                                  "keeps_current_mentor": fname.get(existing_fac[t.id]), **_team_domain_info(t)})
    out["unassigned"].sort(key=lambda u: u["team_id"])

    for old in db.scalars(select(AllocationPreview).where(AllocationPreview.cycle_id == cycle.id,
                                                          AllocationPreview.status == "pending")):
        old.status = "discarded"
    summ = workload.summary(db, cycle)
    run = out["summary_run"]
    run["teams_requiring_resolution"] = len(out["unassigned"])
    prev = AllocationPreview(cycle_id=cycle.id, created_by=admin.id, status="pending", payload={
        "assignments": out["assignments"], "unassigned": out["unassigned"],
        "faculty_projection": out["faculty_projection"], "solver": out["solver"],
        "options": {"reoptimize": reoptimize, "include_manual": include_manual},
        "resolve_existing": {str(t.id): existing_fac[t.id] for t in solve_existing},
        "resolve_existing_method": {str(t.id): existing_method[t.id] for t in solve_existing},
        "summary": {**{k: summ[k] for k in ("teams_requiring_guides", "eligible_faculty", "total_capacity",
                                            "available_capacity", "capacity_shortage", "capacity_surplus",
                                            "estimated_baseline")}, **run},
        "policy": POLICY})
    db.add(prev)
    audit(db, admin.id, "allocation.preview", "cycle", cycle.id,
          {"assign": len(out["assignments"]), "requires_resolution": len(out["unassigned"]),
           "reoptimize": reoptimize, "include_manual": include_manual, "proved_optimal": out["solver"]["proved_optimal"]})
    db.commit()
    return prev


POLICY = [
    "Mandatory: approved, active, available faculty; capacity above zero; department restriction when enabled; a compatible domain.",
    "1. Give every team a compatible mentor (teams with none are reported for administrative resolution).",
    "2. Minimise the worst overload (nominal capacity may be exceeded only when unavoidable).",
    "3. Minimise total overload.",
    "4. Maximise primary-domain matches, then additional-domain matches (related-domain matches rank last).",
    "5. Prefer mentors matching more of the team's domains (exact matches first, then related).",
    "6. Balance relative utilisation (load ÷ capacity) across mentors.",
    "7. Use secondary preferences (expertise over supported, interests, same department).",
    "8. Deterministic tie-breaking.",
]


# ---------------------------------------------------------------- locking, history, notifications
def _lock_cycle(db: Session, cycle_id: int) -> AllocationCycle:
    """One writer at a time per cycle: every allocation write path starts here."""
    return db.execute(select(AllocationCycle).where(AllocationCycle.id == cycle_id).with_for_update()
                      .execution_options(populate_existing=True)).scalar_one()


def _lock_faculty(db: Session, ids):
    ids = sorted({i for i in ids if i})
    if ids:
        list(db.scalars(select(FacultyProfile).where(FacultyProfile.id.in_(ids)).with_for_update()
                        .execution_options(populate_existing=True)).unique())


def _history(db, cycle_id, team_id, action, old_f, new_f, reason, admin_id, **extra):
    db.add(AllocationHistory(cycle_id=cycle_id, team_id=team_id, action=action, old_faculty_id=old_f,
                             new_faculty_id=new_f, reason=reason, performed_by=admin_id, **extra))


def _announce(db, team: Team, fac: FacultyProfile, changed: bool):
    notify(db, team.leader_user_id, "Guide assignment changed" if changed else "Guide allocated",
           f"Your team '{team.name}' is {'now' if changed else ''} assigned to {fac.user.full_name} ({fac.department}).".replace("  ", " "),
           "guide_changed" if changed else "guide_allocated")
    notify(db, fac.user_id, "New project team assigned", f"Team '{team.name}' ({team.proposal.title}) was assigned to you.",
           "guide_allocated")


def _recommendation(fv: FacView, mt: dict, preview_id=None, source="optimizer") -> dict:
    return {"faculty_id": fv.id, "faculty_name": fv.name, "tier": mt["tier_name"], "score": mt["total"],
            "explanation": "; ".join(mt["notes"]), "preview_id": preview_id, "source": source}


# ---------------------------------------------------------------- commit
def commit_preview(db: Session, admin: User, preview_id: int, confirm: bool, acknowledge_overload: bool = False) -> dict:
    if not confirm:
        raise HTTPException(422, "You must explicitly confirm the allocation preview before committing it.")
    prev0 = db.get(AllocationPreview, preview_id)
    if prev0 is None:
        raise HTTPException(404, "Preview not found.")
    try:
        cycle = _lock_cycle(db, prev0.cycle_id)
        prev = db.execute(select(AllocationPreview).where(AllocationPreview.id == preview_id).with_for_update()
                          .execution_options(populate_existing=True)).scalar_one()
        if prev.status != "pending":
            db.rollback()
            raise HTTPException(409, f"This preview was already {prev.status}. Generate a new preview if needed.")
        _require_open(cycle, True)
        payload = prev.payload
        new_over = payload["summary"].get("new_overload", 0)
        if new_over > 0 and not acknowledge_overload:
            db.rollback()
            raise HTTPException(422, {"code": "overload_ack_required", "new_overload": new_over,
                                      "message": f"This allocation exceeds the nominal capacity of some mentors (+{new_over} "
                                                 "team(s) in total). Review the overload warnings and confirm explicitly."})
        assignments = sorted(payload["assignments"], key=lambda a: a["team_id"])
        resolve_existing = {int(k): v for k, v in payload.get("resolve_existing", {}).items()}
        allowed_over = {p["faculty_id"]: p["overload"] for p in payload["faculty_projection"]}
        _lock_faculty(db, [a["faculty_id"] for a in assignments] + list(resolve_existing.values()))
        parents, names = load_parents(db)
        restrict = restrict_department(db)
        views = {f.id: f for f in fac_views(db, cycle.id, exclude_team_ids=list(resolve_existing))}   # fresh, after locks
        loads = {fid: fv.assigned for fid, fv in views.items()}
        in_plan = {a["team_id"] for a in assignments}
        for tid in resolve_existing:
            if tid not in in_plan:                     # kept with the current mentor: its load stays
                cur = db.scalar(select(Allocation).where(Allocation.team_id == tid).execution_options(populate_existing=True))
                if cur is not None:
                    loads[cur.faculty_id] = loads.get(cur.faculty_id, 0) + 1

        done, reassigned, unchanged, skipped = [], [], [], []
        for a in assignments:
            tid, fid = a["team_id"], a["faculty_id"]
            team = db.get(Team, tid)
            cur = db.scalar(select(Allocation).where(Allocation.team_id == tid).execution_options(populate_existing=True))
            is_resolve = tid in resolve_existing
            fv = views.get(fid)
            problem = None
            if team is None or team.cycle_id != cycle.id:
                problem = "team no longer belongs to this cycle"
            elif is_resolve and (cur is None or cur.status != A_ALLOCATED or cur.faculty_id != resolve_existing[tid]):
                problem = "the team's allocation changed after the preview was created"
            elif is_resolve and cur.method == "manual" and not payload["options"].get("include_manual"):
                problem = "manual assignments are preserved"
            elif not is_resolve and cur is not None:
                problem = "team already has a guide"
            elif not (team.proposal and team.proposal.eligible_for_allocation and
                      team.proposal.status == (P_ALLOCATED if is_resolve else P_APPROVED)):
                problem = "proposal is no longer eligible"
            elif fv is None or fv.status_problem or fv.capacity <= 0:
                problem = fv.status_problem if fv and fv.status_problem else "faculty has no capacity configured"
            else:
                mt = match_pair(team_view(team), fv, parents, names, restrict)
                if not mt["compatible"]:
                    problem = ("faculty is no longer domain-compatible" if mt["domain_compatible"] is False
                               else "faculty no longer satisfies the department restriction")
                elif max(0, loads.get(fid, 0) + 1 - fv.capacity) > allowed_over.get(fid, 0):
                    problem = "the mentor's workload or capacity changed after the preview; overload would exceed what was previewed"
            if problem:
                skipped.append({"team_id": tid, "reason": problem})
                if cur is not None:
                    loads[cur.faculty_id] = loads.get(cur.faculty_id, 0) + 1
                continue
            loads[fid] = loads.get(fid, 0) + 1
            rec = _recommendation(fv, mt, prev.id)
            if is_resolve and cur.faculty_id == fid:
                unchanged.append(tid)
                continue
            if is_resolve:
                old_id, was_manual = cur.faculty_id, cur.method == "manual"
                cur.faculty_id, cur.method, cur.score, cur.explanation = fid, "auto", a["score"], a["explanation"]
                cur.assigned_by, cur.match_tier, cur.matched_domains = admin.id, a["tier"], a["matched_domains"]
                cur.is_override, cur.override_reason, cur.auto_recommendation = False, None, rec
                db.flush()
                _history(db, cycle.id, tid, "auto_reassign", old_id, fid,
                         f"Re-optimised ({a['tier']}-domain match, score {a['score']})"
                         + ("; replaced a manual assignment at the administrator's request" if was_manual else ""), admin.id,
                         details={"tier": a["tier"], "matched_domains": a["matched_domains"], "preview_id": prev.id,
                                  "replaced_manual": was_manual}, projected_load=loads[fid], capacity_at_time=fv.capacity)
                _announce(db, team, db.get(FacultyProfile, fid), True)
                of = db.get(FacultyProfile, old_id)
                notify(db, of.user_id, "Team reassigned", f"Team '{team.name}' was reassigned to another guide.", "guide_changed")
                reassigned.append(tid)
                continue
            db.add(Allocation(cycle_id=cycle.id, team_id=tid, faculty_id=fid, status=A_ALLOCATED, method="auto",
                              score=a["score"], explanation=a["explanation"], assigned_by=admin.id,
                              match_tier=a["tier"], matched_domains=a["matched_domains"], auto_recommendation=rec))
            team.proposal.status = P_ALLOCATED
            _history(db, cycle.id, tid, "auto_assign", None, fid,
                     f"Optimised allocation ({a['tier']}-domain match, score {a['score']})", admin.id,
                     details={"tier": a["tier"], "matched_domains": a["matched_domains"], "preview_id": prev.id},
                     projected_load=loads[fid], capacity_at_time=fv.capacity,
                     capacity_violation=loads[fid] > fv.capacity)
            db.flush()
            _announce(db, team, db.get(FacultyProfile, fid), False)
            done.append(tid)

        over_now = [{"faculty_id": f, "name": views[f].name, "assigned": n, "capacity": views[f].capacity,
                     "overload": n - views[f].capacity} for f, n in sorted(loads.items())
                    if f in views and n > views[f].capacity]
        resolution = len(payload["unassigned"]) + len(skipped)
        msg = f"{len(done) + len(reassigned)} team(s) allocated"
        if over_now:
            msg += f"; {len(over_now)} mentor(s) are above their nominal capacity"
        if resolution:
            msg += f". {resolution} team(s) still require administrative resolution"
        prev.status, prev.committed_at = "committed", utcnow()
        prev.result = {"assigned": done, "reassigned": reassigned, "unchanged": unchanged, "skipped": skipped,
                       "unassigned": payload["unassigned"], "overloaded": over_now,
                       "requires_resolution": resolution, "all_teams_compatible": resolution == 0, "message": msg + "."}
        audit(db, admin.id, "allocation.commit", "cycle", cycle.id,
              {"assigned": len(done), "reassigned": len(reassigned), "skipped": len(skipped),
               "overloaded": len(over_now), "overload_acknowledged": bool(acknowledge_overload)})
        db.commit()
        return prev.result
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


# ---------------------------------------------------------------- manual assignment / administrator override
def manual_check(db: Session, team: Team, fac: FacultyProfile) -> dict:
    """What would happen if an administrator assigned ``team`` to ``fac``? Shared by the preview and commit paths.

    ``problems``  = hard blockers (mandatory rules): nothing can override these.
    ``requires_domain_override`` / ``requires_overload_ack`` = exceptions the administrator may confirm with a reason.
    """
    cycle = team.cycle
    parents, names = load_parents(db)
    restrict = restrict_department(db)
    views = {f.id: f for f in fac_views(db, cycle.id)}
    fv = views[fac.id]
    old = team.allocation
    problems = []
    if not (team.proposal and team.proposal.eligible_for_allocation and
            team.proposal.status in (P_APPROVED, P_ALLOCATED, P_FINALISED)):
        problems.append("the team's proposal is not approved/eligible")
    if old and old.faculty_id == fac.id:
        problems.append("the team is already assigned to this faculty member")
    if fv.status_problem:
        problems.append(f"faculty {fv.status_problem}")
    mt = match_pair(team_view(team), fv, parents, names, restrict)
    if mt["dept_blocked"]:
        problems.append(f"the department restriction is on and the faculty member is not in '{team.department}'")
    domain_ok = mt["domain_compatible"]
    projected = fv.assigned + 1
    cap_exceeded = projected > fv.capacity
    old_fv = views.get(old.faculty_id) if old else None
    warnings = []
    if not domain_ok:
        warnings.append({"code": "no_domain_match", "message":
                         f"{fv.name} has no expertise or supported domain that matches this team (primary, additional or related). "
                         "Assigning them is an administrative override of domain compatibility."})
    if cap_exceeded:
        warnings.append({"code": "over_capacity", "message":
                         (f"{fv.name} would supervise {projected} team(s) against a capacity of {fv.capacity} "
                          f"(overload +{projected - fv.capacity})." if fv.capacity > 0 else
                          f"{fv.name} has a capacity of 0 (no new assignments) and would be given a team.")})
    fac_dom = serialize_faculty_domains(db.get(FacultyProfile, fac.id))
    return {"team_id": team.id, "team_name": team.name, "faculty_id": fac.id, "faculty_name": fv.name,
            "current_faculty": old_fv.name if old_fv else None, "is_reassignment": old is not None,
            "allocation_finalised": bool(old and old.status == A_FINALISED),
            "score": mt["total"], "domain_score": mt["domain_score"], "explanation": "; ".join(mt["notes"]),
            "match_tier": mt["tier_name"] or "none", "matched_domains": mt["matched"], "domain_compatible": domain_ok,
            "team_domains": {"primary": next((td.domain.name for td in team.domains if td.kind == "primary"), None),
                             "additional": sorted(td.domain.name for td in team.domains if td.kind == "interest")},
            "faculty_domains": {k: [d["name"] for d in v] for k, v in fac_dom.items()},
            "faculty_assigned_before": fv.assigned, "faculty_capacity": fv.capacity,
            "faculty_projected": projected, "projected_overload": max(0, projected - fv.capacity),
            "faculty_remaining_after": max(0, fv.capacity - projected),
            "old_faculty_assigned_after": (old_fv.assigned - 1) if old_fv else None,
            "capacity_exceeded": cap_exceeded, "warnings": warnings,
            "problems": problems, "can_assign": not problems,
            "requires_domain_override": not domain_ok, "requires_overload_ack": cap_exceeded,
            "requires_reason": old is not None or not domain_ok or cap_exceeded,
            "is_override": (not domain_ok) or cap_exceeded}


def eligible_faculty_for_team(db: Session, team: Team) -> list[dict]:
    """Every approved faculty member with what an assignment would mean. ``eligible`` = assignable without any exception."""
    parents, names = load_parents(db)
    restrict = restrict_department(db)
    tv = team_view(team)
    out = []
    for fv in fac_views(db, team.cycle_id):
        mt = match_pair(tv, fv, parents, names, restrict)
        blocked = fv.status_problem or (
            "department restriction" if mt["dept_blocked"] else None)
        exceeded = fv.assigned + 1 > fv.capacity
        if blocked:
            reason = blocked
        elif not mt["domain_compatible"]:
            reason = "no compatible domain (administrator override required)"
        elif exceeded:
            reason = f"capacity reached ({fv.assigned}/{fv.capacity}); would be overloaded"
        else:
            reason = None
        out.append({"faculty_id": fv.id, "name": fv.name, "department": fv.department, "assigned": fv.assigned,
                    "capacity": fv.capacity, "remaining": fv.remaining, "score": mt["total"],
                    "domain_score": mt["domain_score"], "explanation": "; ".join(mt["notes"]),
                    "match_tier": mt["tier_name"] or "none", "domain_compatible": mt["domain_compatible"],
                    "eligible": reason is None, "ineligible_reason": reason, "blocked": bool(blocked),
                    "override_possible": blocked is None and reason is not None,
                    "projected_overload": max(0, fv.assigned + 1 - fv.capacity)})
    out.sort(key=lambda r: (r["blocked"], not r["eligible"], r["match_tier"] == "none",
                            {"primary": 0, "additional": 1, "related": 2, "none": 3}[r["match_tier"]], -r["score"], r["faculty_id"]))
    return out


def assign_manual(db: Session, admin: User, team_id: int, faculty_id: int, reason: str, confirm: bool,
                  override_domain: bool = False, acknowledge_overload: bool = False) -> Allocation:
    if not confirm:
        raise HTTPException(422, "Please confirm the assignment after reviewing the preview.")
    team0 = db.get(Team, team_id)
    if team0 is None or db.get(FacultyProfile, faculty_id) is None:
        raise HTTPException(404, "Team or faculty member not found.")
    reason = (reason or "").strip()
    try:
        cycle = _lock_cycle(db, team0.cycle_id)
        _require_open(cycle, False)
        _lock_faculty(db, [faculty_id])
        team = db.execute(select(Team).where(Team.id == team_id).execution_options(populate_existing=True)).scalar_one()
        db.refresh(team, ["allocation"])
        fac = db.get(FacultyProfile, faculty_id)
        chk = manual_check(db, team, fac)
        if not chk["can_assign"]:
            raise HTTPException(409, "Assignment not allowed: " + "; ".join(chk["problems"]) + ".")
        if chk["requires_domain_override"] and not override_domain:
            raise HTTPException(409, {"code": "domain_override_required", "message":
                                      f"{chk['faculty_name']} has no compatible domain for this team. Confirm the administrative "
                                      "override explicitly (with a reason) to assign them anyway."})
        if chk["requires_overload_ack"] and not acknowledge_overload:
            raise HTTPException(409, {"code": "overload_ack_required", "message":
                                      f"{chk['faculty_name']} would exceed their capacity ({chk['faculty_projected']}/"
                                      f"{chk['faculty_capacity']}). Acknowledge the overload explicitly (with a reason) to continue."})
        old = team.allocation
        if chk["requires_reason"] and len(reason) < 3:
            raise HTTPException(422, "A reason is required for a reassignment or an override of domain compatibility/capacity.")
        parents, names = load_parents(db)
        views = {f.id: f for f in fac_views(db, cycle.id)}
        fv = views[fac.id]
        # keep the ORIGINAL automatic recommendation for audit and comparison
        mt_all = [(match_pair(team_view(team), v, parents, names, restrict_department(db)), v) for v in views.values()
                  if v.status_problem is None and v.capacity > 0]
        compat = sorted([(m["tier"], -m["total"], v.id, m, v) for m, v in mt_all if m["compatible"]], key=lambda r: r[:3])
        engine_rec = _recommendation(compat[0][4], compat[0][3], source="engine-at-assignment") if compat else None
        auto_rec = (old.auto_recommendation if old is not None and old.auto_recommendation else engine_rec)
        final = cycle.status == CYCLE_FINALISED
        tier_label = "override" if chk["requires_domain_override"] else chk["match_tier"]
        is_ovr = chk["is_override"]
        details = {"tier": chk["match_tier"], "matched_domains": chk["matched_domains"], "auto_recommendation": auto_rec,
                   "previous_method": old.method if old else None, "overload_acknowledged": bool(chk["capacity_exceeded"])}
        if old is None:
            alloc = Allocation(cycle_id=cycle.id, team_id=team.id, faculty_id=fac.id, method="manual", score=chk["score"],
                               explanation=chk["explanation"], assigned_by=admin.id,
                               status=A_FINALISED if final else A_ALLOCATED, finalised_at=utcnow() if final else None,
                               match_tier=tier_label, matched_domains=chk["matched_domains"], is_override=is_ovr,
                               override_reason=reason if is_ovr else None, auto_recommendation=auto_rec)
            db.add(alloc)
            action, old_id = "manual_assign", None
        else:
            alloc, old_id = old, old.faculty_id
            alloc.faculty_id, alloc.method, alloc.score = fac.id, "manual", chk["score"]
            alloc.explanation, alloc.assigned_by = chk["explanation"], admin.id
            alloc.match_tier, alloc.matched_domains = tier_label, chk["matched_domains"]
            alloc.is_override, alloc.override_reason = is_ovr, (reason if is_ovr else None)
            alloc.auto_recommendation = auto_rec
            action = "reassign"
        team.proposal.status = P_FINALISED if alloc.status == A_FINALISED else P_ALLOCATED
        _history(db, cycle.id, team.id, action, old_id, fac.id, reason, admin.id, is_override=is_ovr,
                 domain_violation=chk["requires_domain_override"], capacity_violation=chk["capacity_exceeded"],
                 projected_load=chk["faculty_projected"], capacity_at_time=chk["faculty_capacity"], details=details)
        db.flush()
        _announce(db, team, fac, old is not None)
        if old_id:
            of = db.get(FacultyProfile, old_id)
            notify(db, of.user_id, "Team reassigned", f"Team '{team.name}' was reassigned to another guide.", "guide_changed")
        audit(db, admin.id, f"allocation.{action}", "team", team.id,
              {"old_faculty_id": old_id, "new_faculty_id": fac.id, "reason": reason, "override": is_ovr,
               "domain_violation": chk["requires_domain_override"], "capacity_violation": chk["capacity_exceeded"],
               "projected_load": chk["faculty_projected"], "capacity": chk["faculty_capacity"],
               "auto_recommendation": auto_rec})
        db.commit()
        return alloc
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


def unassign(db: Session, admin: User, team_id: int, reason: str, confirm: bool) -> None:
    if not confirm:
        raise HTTPException(422, "Please confirm removing the guide assignment.")
    team0 = db.get(Team, team_id)
    if team0 is None:
        raise HTTPException(404, "Team not found.")
    try:
        cycle = _lock_cycle(db, team0.cycle_id)
        _require_open(cycle, False)
        alloc = db.scalar(select(Allocation).where(Allocation.team_id == team_id).execution_options(populate_existing=True))
        if alloc is None:
            raise HTTPException(409, "This team has no guide assigned.")
        team = db.get(Team, team_id)
        old_f = alloc.faculty_id
        fac = db.get(FacultyProfile, old_f)
        db.delete(alloc)
        team.proposal.status = P_APPROVED
        _history(db, cycle.id, team.id, "unassign", old_f, None, reason, admin.id)
        notify(db, team.leader_user_id, "Guide assignment removed", f"The guide assignment for '{team.name}' was removed; "
               "a new guide will be allocated.", "guide_changed")
        notify(db, fac.user_id, "Team unassigned", f"Team '{team.name}' was removed from your workload.", "guide_changed")
        audit(db, admin.id, "allocation.unassign", "team", team.id, {"old_faculty_id": old_f, "reason": reason})
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


# ---------------------------------------------------------------- finalisation
def finalise_cycle(db: Session, admin: User, cycle_id: int, confirm: bool, acknowledge_overload: bool = False) -> dict:
    if not confirm:
        raise HTTPException(422, "Finalisation is irreversible without an audited admin override. Please confirm.")
    try:
        cycle = _lock_cycle(db, cycle_id)
        if cycle.status == CYCLE_FINALISED:
            raise HTTPException(409, "This cycle is already finalised.")
        if cycle.status != CYCLE_ACTIVE:
            raise HTTPException(409, f"Only an active cycle can be finalised (this one is '{cycle.status}').")
        allocs = list(db.scalars(select(Allocation).where(Allocation.cycle_id == cycle.id)
                                 .execution_options(populate_existing=True)).unique())
        if not allocs:
            raise HTTPException(409, "There are no allocations to finalise.")
        caps, counts = workload.capacity_map(db, cycle.id), workload.assigned_counts(db, cycle.id)
        problems, overloads = [], []
        for fid, n in counts.items():
            f = db.get(FacultyProfile, fid)
            cap = caps.get(fid, f.max_capacity)
            if f.approval_status != FAC_APPROVED or not f.user.is_active:
                problems.append(f"{f.user.full_name} is no longer an approved, active faculty member")
            if n > cap:
                overloads.append({"faculty_id": fid, "name": f.user.full_name, "assigned": n, "capacity": cap, "overload": n - cap})
        for a in allocs:
            p = db.scalar(select(Proposal).where(Proposal.team_id == a.team_id))
            if p is None or not p.eligible_for_allocation or p.status != P_ALLOCATED:
                problems.append(f"Team id {a.team_id} no longer has an eligible allocated proposal")
        dup = db.execute(select(Allocation.team_id).where(Allocation.cycle_id == cycle.id).group_by(Allocation.team_id)
                         .having(func.count() > 1)).all()
        if dup:
            problems.append("duplicate allocations detected")
        over_text = [f"{o['name']} has {o['assigned']} teams but capacity is {o['capacity']}" for o in overloads]
        if problems or (overloads and not acknowledge_overload):
            msgs = problems + over_text
            raise HTTPException(409, {"code": "finalise_blocked",
                                      "message": "Finalisation blocked: " + "; ".join(msgs) + ". Resolve these (reassign or adjust "
                                                 "capacity)" + (", or acknowledge the overload explicitly" if not problems else "") + " and retry.",
                                      "problems": msgs, "overloads": overloads,
                                      "acknowledgeable": bool(overloads) and not problems})
        now = utcnow()
        for a in allocs:
            a.status, a.finalised_at = A_FINALISED, now
            db.scalar(select(Proposal).where(Proposal.team_id == a.team_id)).status = P_FINALISED
            team = db.get(Team, a.team_id)
            _history(db, cycle.id, a.team_id, "finalise", a.faculty_id, a.faculty_id, "Allocation finalised", admin.id)
            notify(db, team.leader_user_id, "Allocation finalised", f"Your guide allocation for '{team.name}' is final.", "allocation_finalised")
        for fid in counts:
            notify(db, db.get(FacultyProfile, fid).user_id, "Allocation finalised",
                   f"Allocations for {cycle.name} were finalised; your assigned teams are now official.", "allocation_finalised")
        # snapshot each approved faculty member's capacity so history stays correct after later edits
        for f in db.scalars(select(FacultyProfile).where(FacultyProfile.approval_status == FAC_APPROVED)).unique():
            if f.id not in caps:
                db.add(FacultyCycleCapacity(faculty_id=f.id, cycle_id=cycle.id, max_capacity=f.max_capacity))
        cycle.status, cycle.finalised_at = CYCLE_FINALISED, now
        audit(db, admin.id, "allocation.finalise", "cycle", cycle.id,
              {"allocations": len(allocs), "overloads_acknowledged": overloads if overloads else []})
        db.commit()
        return {"finalised": len(allocs), "cycle_id": cycle.id, "overloaded": overloads}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
