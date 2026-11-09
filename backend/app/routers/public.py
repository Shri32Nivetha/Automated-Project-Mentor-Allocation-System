from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import Domain
from ..schemas import DomainOut, FacultyRegisterIn, TeamRegisterIn
from ..services import faculty as fsvc
from ..services import teams as tsvc
from ..services import workload as wl
from ..services.common import active_cycle, get_setting

router = APIRouter(tags=["public"])


@router.get("/meta")
def meta(db: Session = Depends(get_db)):
    cyc = active_cycle(db, required=False)
    return {
        "active_cycle": None if not cyc else {"id": cyc.id, "name": cyc.name, "academic_year": cyc.academic_year,
                                              "status": cyc.status, "registration_deadline": cyc.registration_deadline,
                                              "proposal_deadline": cyc.proposal_deadline},
        "team_rules": {"min_team_size": get_setting(db, "min_team_size"), "max_team_size": get_setting(db, "max_team_size"),
                       "allow_cross_department": get_setting(db, "allow_cross_department"),
                       "allow_cross_programme": get_setting(db, "allow_cross_programme"),
                       "allowed_email_domains": get_setting(db, "allowed_email_domains")},
        "designations": list((get_setting(db, "designation_capacity_defaults") or {}).keys()),
        "email_delivery_enabled": get_settings().email_enabled,
    }


@router.get("/domains", response_model=list[DomainOut])
def public_domains(db: Session = Depends(get_db)):
    """Active catalogue entries (user-submitted custom domains that are still pending are not listed)."""
    return db.scalars(select(Domain).where(Domain.is_active == True, Domain.is_custom == False)  # noqa: E712
                      .order_by(Domain.is_other, Domain.name)).all()


@router.post("/register/team", status_code=201)
def register_team(data: TeamRegisterIn, db: Session = Depends(get_db)):
    team = tsvc.register_team(db, data)
    return {"team_id": team.id, "team_name": team.name, "members": len(team.members),
            "message": "Team registered. Sign in with the leader's e-mail and password."}


@router.post("/register/faculty", status_code=201)
def register_faculty(data: FacultyRegisterIn, db: Session = Depends(get_db)):
    prof = fsvc.register_faculty(db, data)
    return {"faculty_id": prof.id, "approval_status": prof.approval_status,
            "message": "Registration received. An administrator must approve it before you can receive teams."}
