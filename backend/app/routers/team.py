"""Team-leader endpoints. Ownership always derives from the authenticated leader (leader_team dependency)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import leader_team, require_leader
from ..models import Team, TeamChangeRequest, TeamMember, User
from ..schemas import ChangeRequestIn, MemberIn, MemberUpdateIn, ProposalIn, TeamUpdateIn
from ..services import proposals as psvc
from ..services import teams as tsvc
from ..services.common import audit, notify

router = APIRouter(prefix="/team", tags=["team leader"])


def _fresh(db: Session, team_id: int) -> Team:
    db.expire_all()
    return db.get(Team, team_id)


@router.get("")
def my_team(team: Team = Depends(leader_team)):
    return tsvc.serialize_team(team)


@router.put("")
def update_team(data: TeamUpdateIn, team: Team = Depends(leader_team), user: User = Depends(require_leader),
                db: Session = Depends(get_db)):
    tsvc.assert_leader_can_edit(team)
    tsvc.update_team(db, team, data, user.id)
    db.commit()
    return tsvc.serialize_team(_fresh(db, team.id))


@router.post("/members", status_code=201)
def add_member(data: MemberIn, team: Team = Depends(leader_team), user: User = Depends(require_leader),
               db: Session = Depends(get_db)):
    tsvc.assert_leader_can_edit(team)
    m = tsvc.add_member(db, team, data, user.id)
    db.commit()
    return tsvc.serialize_member(m)


@router.put("/members/{member_id}")
def update_member(member_id: int, data: MemberUpdateIn, team: Team = Depends(leader_team),
                  user: User = Depends(require_leader), db: Session = Depends(get_db)):
    tsvc.assert_leader_can_edit(team)
    m = db.get(TeamMember, member_id)
    if m is None or m.team_id != team.id:
        raise HTTPException(404, "Member not found in your team.")
    tsvc.update_member(db, team, m, data, user.id)
    db.commit()
    return tsvc.serialize_member(m)


@router.delete("/members/{member_id}", status_code=204)
def remove_member(member_id: int, team: Team = Depends(leader_team), user: User = Depends(require_leader),
                  db: Session = Depends(get_db)):
    tsvc.assert_leader_can_edit(team)
    m = db.get(TeamMember, member_id)
    if m is None or m.team_id != team.id:
        raise HTTPException(404, "Member not found in your team.")
    tsvc.remove_member(db, team, m, user.id)
    db.commit()


@router.get("/proposal")
def get_proposal(team: Team = Depends(leader_team)):
    return tsvc.serialize_proposal(team.proposal, team)


@router.put("/proposal")
def save_proposal(data: ProposalIn, team: Team = Depends(leader_team), user: User = Depends(require_leader),
                  db: Session = Depends(get_db)):
    psvc.save_proposal(db, team, data, user.id)
    return tsvc.serialize_proposal(_fresh(db, team.id).proposal, _fresh(db, team.id))


@router.post("/proposal/submit")
def submit_proposal(team: Team = Depends(leader_team), user: User = Depends(require_leader),
                    db: Session = Depends(get_db)):
    psvc.submit_proposal(db, team, user.id)
    t = _fresh(db, team.id)
    return tsvc.serialize_proposal(t.proposal, t)


@router.get("/guide")
def my_guide(team: Team = Depends(leader_team)):
    return {"allocation": tsvc.serialize_allocation(team)}


@router.post("/change-requests", status_code=201)
def create_change_request(data: ChangeRequestIn, team: Team = Depends(leader_team), user: User = Depends(require_leader),
                          db: Session = Depends(get_db)):
    """After finalisation the leader cannot edit membership; they ask an admin, who applies the change."""
    if tsvc.edit_block(team) is None:
        raise HTTPException(409, "Your team can still be edited directly; a change request is not needed.")
    cr = TeamChangeRequest(team_id=team.id, requested_by=user.id, description=data.description)
    db.add(cr)
    audit(db, user.id, "team.change_request", "team", team.id)
    db.commit()
    return {"id": cr.id, "status": cr.status}


@router.get("/change-requests")
def list_change_requests(team: Team = Depends(leader_team), db: Session = Depends(get_db)):
    rows = db.scalars(select(TeamChangeRequest).where(TeamChangeRequest.team_id == team.id)
                      .order_by(TeamChangeRequest.id.desc())).all()
    return [{"id": r.id, "description": r.description, "status": r.status, "admin_remarks": r.admin_remarks,
             "created_at": r.created_at, "resolved_at": r.resolved_at} for r in rows]
