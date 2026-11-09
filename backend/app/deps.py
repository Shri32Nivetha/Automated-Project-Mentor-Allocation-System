from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import ROLE_ADMIN, ROLE_FACULTY, ROLE_LEADER, FacultyProfile, Team, User
from .security import decode_token

bearer = HTTPBearer(auto_error=False)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                 db: Session = Depends(get_db)) -> User:
    err = HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session is invalid or has expired. Please sign in again.",
                        headers={"WWW-Authenticate": "Bearer"})
    if creds is None:
        raise err
    payload = decode_token(creds.credentials)
    if not payload:
        raise err
    try:
        user = db.get(User, int(payload.get("sub", 0)))
    except (TypeError, ValueError):
        raise err
    # Role, active flag and token version always come from the database, never from the client.
    if user is None or not user.is_active or payload.get("tv") != user.token_version:
        raise err
    return user


def require_role(*roles: str):
    def checker(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "You do not have permission to perform this action.")
        return user
    return checker


require_admin = require_role(ROLE_ADMIN)
require_faculty = require_role(ROLE_FACULTY)
require_leader = require_role(ROLE_LEADER)


def leader_team(user: User = Depends(require_leader), db: Session = Depends(get_db)) -> Team:
    """The team-leader's own team (latest cycle). Ownership is derived from the token, never from the URL."""
    team = db.scalar(select(Team).where(Team.leader_user_id == user.id).order_by(Team.cycle_id.desc()).limit(1))
    if team is None:
        raise HTTPException(404, "No team is registered for this account.")
    return team


def faculty_profile(user: User = Depends(require_faculty), db: Session = Depends(get_db)) -> FacultyProfile:
    prof = db.scalar(select(FacultyProfile).where(FacultyProfile.user_id == user.id))
    if prof is None:
        raise HTTPException(404, "Faculty profile not found.")
    return prof
