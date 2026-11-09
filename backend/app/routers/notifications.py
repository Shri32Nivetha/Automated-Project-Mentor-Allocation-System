from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import current_user
from ..models import Notification, User
from ..services.common import paginate

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _out(n: Notification):
    return {"id": n.id, "title": n.title, "message": n.message, "kind": n.kind, "is_read": n.is_read,
            "created_at": n.created_at}


@router.get("")
def list_notifications(page: int = 1, page_size: int = 20, unread_only: bool = False,
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Notification).where(Notification.user_id == user.id).order_by(Notification.id.desc())
    if unread_only:
        stmt = stmt.where(Notification.is_read == False)  # noqa: E712
    r = paginate(db, stmt, page, page_size)
    r["items"] = [_out(n) for n in r["items"]]
    return r


@router.get("/unread-count")
def unread_count(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"unread": db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == user.id, Notification.is_read == False)) or 0}  # noqa: E712


@router.post("/{nid}/read")
def mark_read(nid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, nid)
    if n is None or n.user_id != user.id:
        raise HTTPException(404, "Notification not found.")
    n.is_read = True
    db.commit()
    return _out(n)


@router.post("/read-all")
def mark_all(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(update(Notification).where(Notification.user_id == user.id, Notification.is_read == False)  # noqa: E712
               .values(is_read=True))
    db.commit()
    return {"ok": True}
