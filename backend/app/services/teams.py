"""Team registration (one form, one leader login) and team editing rules."""
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import utcnow
from ..models import (A_FINALISED, CYCLE_ACTIVE, P_DRAFT, P_REVISION, ROLE_LEADER, AllocationCycle, Proposal,
                      Team, TeamMember, User)
from ..schemas import TeamRegisterIn
from ..security import hash_password, verify_password
from .common import active_cycle, audit, get_setting, norm_email, norm_name, norm_regno, notify, validate_regno, check_institutional_email


def _aware(dt):
    return dt


def ensure_registration_open(cycle: AllocationCycle) -> None:
    if cycle.status != CYCLE_ACTIVE:
        raise HTTPException(409, f"Registration is closed: cycle '{cycle.name}' is {cycle.status}.")
    if cycle.registration_deadline and utcnow() > cycle.registration_deadline:
        raise HTTPException(409, "The team registration deadline for this cycle has passed.")


def check_size(db: Session, count: int) -> None:
    lo, hi = int(get_setting(db, "min_team_size")), int(get_setting(db, "max_team_size"))
    if count < lo or count > hi:
        raise HTTPException(422, f"A team must have between {lo} and {hi} students (leader included); you entered {count}.")


def check_email_domain(db: Session, email: str) -> None:
    allowed = [d.strip().lower().lstrip("@") for d in str(get_setting(db, "allowed_email_domains") or "").split(",") if d.strip()]
    if allowed and email.rsplit("@", 1)[-1] not in allowed:
        raise HTTPException(422, f"{email} is not an institutional e-mail address (allowed: {', '.join(allowed)}).")


def check_member_rules(db: Session, team_dept: str, team_prog: str, members: list[dict]) -> None:
    cross_dept = bool(get_setting(db, "allow_cross_department"))
    cross_prog = bool(get_setting(db, "allow_cross_programme"))
    for m in members:
        if not cross_dept and m["department"].lower() != team_dept.lower():
            raise HTTPException(422, f"{m['full_name']}: department '{m['department']}' differs from the team's department "
                                     f"'{team_dept}'. Cross-department teams are not allowed.")
        if not cross_prog and m["programme"].lower() != team_prog.lower():
            raise HTTPException(422, f"{m['full_name']}: programme '{m['programme']}' differs from the team's programme "
                                     f"'{team_prog}'. Cross-programme teams are not allowed.")


def check_duplicates(db: Session, cycle_id: int, members: list[dict], ignore_member_ids: set[int] = frozenset()) -> None:
    emails, regs = [m["email"] for m in members], [m["registration_number"] for m in members]
    if len(set(emails)) != len(emails):
        raise HTTPException(422, "The same e-mail address is used for more than one team member.")
    if len(set(regs)) != len(regs):
        raise HTTPException(422, "The same registration number is used for more than one team member.")
    rows = db.scalars(select(TeamMember).where(TeamMember.cycle_id == cycle_id,
                                               (TeamMember.email.in_(emails)) | (TeamMember.registration_number.in_(regs))))
    for r in rows:
        if r.id in ignore_member_ids:
            continue
        if r.registration_number in regs:
            raise HTTPException(409, f"Registration number {r.registration_number} is already registered in a team for this cycle.")
        raise HTTPException(409, f"E-mail {r.email} is already registered in a team for this cycle.")


def _member_dict(m, team_dept, team_prog, team_year) -> dict:
    return {"full_name": norm_name(m.full_name), "email": norm_email(m.email),
            "registration_number": norm_regno(m.registration_number),
            "department": norm_name(m.department or team_dept), "programme": norm_name(m.programme or team_prog),
            "year_semester": norm_name(m.year_semester or team_year)}


def register_team(db: Session, data: TeamRegisterIn) -> Team:
    cycle = active_cycle(db)
    if data.cycle_id is not None and data.cycle_id != cycle.id:
        raise HTTPException(409, "Registration is only open for the active allocation cycle.")
    ensure_registration_open(cycle)
    check_size(db, data.number_of_members)
    dept, prog, year = norm_name(data.department), norm_name(data.programme), norm_name(data.year_semester)
    people = [_member_dict(data.leader, dept, prog, year)] + [_member_dict(m, dept, prog, year) for m in data.members]
    for p in people:
        check_institutional_email(p["email"])      # leader + every member: @srmist.edu.in only
        check_email_domain(db, p["email"])
    check_member_rules(db, dept, prog, people)
    check_duplicates(db, cycle.id, people)
    name = norm_name(data.team_name)
    if db.scalar(select(Team.id).where(Team.cycle_id == cycle.id, Team.name == name)):
        raise HTTPException(409, f"A team named '{name}' already exists in this cycle.")

    leader_email = people[0]["email"]
    user = db.scalar(select(User).where(User.email == leader_email))
    if user is not None:
        # An existing team-leader account may register a new team in a NEW cycle by proving its password.
        if user.role != ROLE_LEADER or not verify_password(data.leader.password, user.password_hash):
            raise HTTPException(409, "This e-mail address already has an account. Sign in, or use a different e-mail.")
        if db.scalar(select(Team.id).where(Team.leader_user_id == user.id, Team.cycle_id == cycle.id)):
            raise HTTPException(409, "This leader already registered a team in this cycle.")
    else:
        user = User(email=leader_email, full_name=people[0]["full_name"], role=ROLE_LEADER,
                    password_hash=hash_password(data.leader.password))
        db.add(user)
        db.flush()
    try:
        team = Team(cycle_id=cycle.id, leader_user_id=user.id, name=name, department=dept, programme=prog, year_semester=year)
        for i, p in enumerate(people):
            team.members.append(TeamMember(cycle_id=cycle.id, is_leader=(i == 0), **p))
        team.proposal = Proposal(status=P_DRAFT, technologies=[])
        db.add(team)
        db.flush()
        notify(db, user.id, "Team registered", f"Team '{name}' was registered with {len(people)} members. "
                                                "Next, complete and submit your project proposal.", "team_registered")
        audit(db, user.id, "team.register", "team", team.id, {"members": len(people), "cycle_id": cycle.id})
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A duplicate team, registration number or e-mail was detected. Please review your entries.")
    return team


def edit_block(team: Team) -> tuple[str, str] | None:
    """Why a *team leader* cannot currently edit the team / proposal, or None if editing is allowed."""
    alloc = team.allocation
    if team.cycle.status in ("finalised", "archived") or (alloc and alloc.status == A_FINALISED):
        return "finalised", ("Allocation has been finalised. Membership changes now require administrator approval: "
                             "submit a change request.")
    st = team.proposal.status if team.proposal else P_DRAFT
    if st not in (P_DRAFT, P_REVISION):
        return "submitted", "The proposal has been submitted, so team and proposal details are locked."
    dl = team.cycle.proposal_deadline
    if dl and utcnow() > dl:
        return "deadline", "The submission deadline has passed. Contact the administrator for changes."
    return None


def assert_leader_can_edit(team: Team) -> None:
    b = edit_block(team)
    if b:
        raise HTTPException(409 if b[0] != "finalised" else 403, b[1])


def serialize_member(m: TeamMember) -> dict:
    return {k: getattr(m, k) for k in ("id", "full_name", "email", "registration_number", "department",
                                       "programme", "year_semester", "is_leader")}


def serialize_domains(team: Team) -> dict:
    prim = next((td.domain for td in team.domains if td.kind == "primary"), None)
    dd = lambda d: {"id": d.id, "name": d.name, "is_custom": d.is_custom, "custom_status": d.custom_status}
    return {"primary": dd(prim) if prim else None,
            "interests": [dd(td.domain) for td in team.domains if td.kind == "interest"]}


def serialize_proposal(p: Proposal | None, team: Team) -> dict | None:
    if p is None:
        return None
    d = serialize_domains(team)
    return {"id": p.id, "title": p.title, "description": p.description, "technologies": p.technologies or [],
            "objectives": p.objectives, "expected_outcomes": p.expected_outcomes, "status": p.status,
            "eligible_for_allocation": p.eligible_for_allocation, "admin_remarks": p.admin_remarks,
            "submitted_at": p.submitted_at, "updated_at": p.updated_at,
            "primary_domain": d["primary"], "interest_domains": d["interests"],
            "reviews": [{"id": r.id, "from_status": r.from_status, "to_status": r.to_status,
                         "remarks": r.remarks, "created_at": r.created_at} for r in p.reviews]}


def serialize_allocation(team: Team) -> dict | None:
    a = team.allocation
    if a is None:
        return None
    f = a.faculty
    return {"id": a.id, "status": a.status, "method": a.method, "assigned_at": a.created_at,
            "finalised_at": a.finalised_at,
            "faculty": {"id": f.id, "name": f.user.full_name, "email": f.user.email,
                        "department": f.department, "designation": f.designation}}


def serialize_team(team: Team, include_reviews: bool = True) -> dict:
    block = edit_block(team)
    return {"id": team.id, "name": team.name, "department": team.department, "programme": team.programme,
            "year_semester": team.year_semester, "created_at": team.created_at,
            "cycle": {"id": team.cycle.id, "name": team.cycle.name, "status": team.cycle.status,
                      "proposal_deadline": team.cycle.proposal_deadline},
            "leader": {"id": team.leader.id, "name": team.leader.full_name, "email": team.leader.email},
            "members": [serialize_member(m) for m in team.members],
            "domains": serialize_domains(team),
            "proposal": serialize_proposal(team.proposal, team),
            "allocation": serialize_allocation(team),
            "editable": block is None, "edit_block_code": block[0] if block else None,
            "edit_block_reason": block[1] if block else None}


def add_member(db: Session, team: Team, data, actor_id: int, is_admin: bool = False) -> TeamMember:
    hi = int(get_setting(db, "max_team_size"))
    if len(team.members) + 1 > hi:
        raise HTTPException(422, f"A team can have at most {hi} students.")
    p = _member_dict(data, team.department, team.programme, team.year_semester)
    check_institutional_email(p["email"])
    check_email_domain(db, p["email"])
    check_member_rules(db, team.department, team.programme, [p])
    check_duplicates(db, team.cycle_id, [p])
    m = TeamMember(team_id=team.id, cycle_id=team.cycle_id, is_leader=False, **p)
    db.add(m)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Duplicate registration number or e-mail for this cycle.")
    audit(db, actor_id, "team.member_add" if not is_admin else "admin.team_member_add", "team", team.id,
          {"member": p["registration_number"]})
    return m


def update_member(db: Session, team: Team, member: TeamMember, data, actor_id: int, is_admin: bool = False) -> TeamMember:
    changes = data.model_dump(exclude_unset=True)
    if member.is_leader and "email" in changes and norm_email(changes["email"]) != member.email:
        raise HTTPException(422, "The leader's e-mail is the login address and cannot be changed here.")
    cur = {"full_name": member.full_name, "email": member.email, "registration_number": member.registration_number,
           "department": member.department, "programme": member.programme, "year_semester": member.year_semester}
    for k, v in changes.items():
        if v is not None:
            cur[k] = norm_email(v) if k == "email" else norm_regno(v) if k == "registration_number" else norm_name(v)
    if cur["registration_number"] != member.registration_number:
        # Only a CHANGED register number must match the official format; legacy records stay editable otherwise.
        try:
            cur["registration_number"] = validate_regno(cur["registration_number"])
        except ValueError as e:
            raise HTTPException(422, str(e))
    if cur["email"] != member.email:
        check_institutional_email(cur["email"])    # only a CHANGED address is checked; legacy records stay editable
    check_email_domain(db, cur["email"])
    check_member_rules(db, team.department, team.programme, [cur])
    check_duplicates(db, team.cycle_id, [cur], ignore_member_ids={member.id})
    for k, v in cur.items():
        setattr(member, k, v)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Duplicate registration number or e-mail for this cycle.")
    audit(db, actor_id, "team.member_update" if not is_admin else "admin.team_member_update", "team", team.id,
          {"member_id": member.id, "fields": list(changes)})
    return member


def remove_member(db: Session, team: Team, member: TeamMember, actor_id: int, is_admin: bool = False) -> None:
    if member.is_leader:
        raise HTTPException(422, "The team leader cannot be removed. An administrator can reassign leadership.")
    lo = int(get_setting(db, "min_team_size"))
    if len(team.members) - 1 < lo:
        raise HTTPException(422, f"A team must keep at least {lo} students.")
    audit(db, actor_id, "team.member_remove" if not is_admin else "admin.team_member_remove", "team", team.id,
          {"registration_number": member.registration_number})
    team.members.remove(member)
    db.flush()


def update_team(db: Session, team: Team, data, actor_id: int, is_admin: bool = False) -> Team:
    changes = {k: norm_name(v) for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if "name" in changes and changes["name"] != team.name and db.scalar(
            select(Team.id).where(Team.cycle_id == team.cycle_id, Team.name == changes["name"], Team.id != team.id)):
        raise HTTPException(409, "A team with that name already exists in this cycle.")
    new_dept, new_prog = changes.get("department", team.department), changes.get("programme", team.programme)
    check_member_rules(db, new_dept, new_prog, [serialize_member(m) for m in team.members])
    for k, v in changes.items():
        setattr(team, k, v)
    audit(db, actor_id, "team.update" if not is_admin else "admin.team_update", "team", team.id, changes)
    db.flush()
    return team
