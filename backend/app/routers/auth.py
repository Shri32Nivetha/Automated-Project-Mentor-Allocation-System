from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db, utcnow
from ..deps import current_user
from ..models import PasswordResetToken, User
from ..schemas import LoginIn, PasswordChangeIn, ResetConfirmIn, ResetRequestIn, UserOut
from ..security import (create_access_token, hash_password, hash_reset_token, login_limiter, new_reset_token,
                        verify_password)
from ..services.common import audit, norm_email
from ..services.mailer import send_email

router = APIRouter(prefix="/auth", tags=["auth"])
_DUMMY_HASH = hash_password("dummy-password-for-timing")


@router.post("/login")
def login(data: LoginIn, request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    email = norm_email(data.email)
    key = f"{request.client.host if request.client else '?'}|{email}"
    if not login_limiter.check(key, s.login_max_attempts, s.login_window_seconds):
        raise HTTPException(429, "Too many failed sign-in attempts. Please wait a few minutes and try again.")
    user = db.scalar(select(User).where(User.email == email))
    ok = verify_password(data.password, user.password_hash if user else _DUMMY_HASH)  # constant-ish time
    if not user or not ok:
        login_limiter.hit(key)
        raise HTTPException(401, "Incorrect e-mail or password.")
    if not user.is_active:
        raise HTTPException(403, "This account has been deactivated. Contact the administrator.")
    login_limiter.reset(key)
    user.last_login_at = utcnow()
    db.commit()
    return {"access_token": create_access_token(user), "token_type": "bearer", "user": UserOut.model_validate(user)}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@router.post("/change-password")
def change_password(data: PasswordChangeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(422, "Current password is incorrect.")
    user.password_hash = hash_password(data.new_password)
    user.token_version += 1  # signs out every other session
    audit(db, user.id, "auth.password_change", "user", user.id)
    db.commit()
    return {"message": "Password changed. Please sign in again.", "access_token": create_access_token(user)}


@router.post("/password-reset/request")
def reset_request(data: ResetRequestIn, db: Session = Depends(get_db)):
    """Always answers identically so the endpoint cannot be used to discover registered e-mails.
    A reset link is e-mailed only when SMTP is configured; otherwise an admin can issue a token (see README)."""
    user = db.scalar(select(User).where(User.email == norm_email(data.email)))
    if user and user.is_active:
        raw, hashed = new_reset_token()
        db.add(PasswordResetToken(user_id=user.id, token_hash=hashed, expires_at=utcnow() + timedelta(hours=1)))
        audit(db, user.id, "auth.reset_requested", "user", user.id)
        db.commit()
        link = f"{get_settings().frontend_base_url}/reset-password?token={raw}"
        send_email(user.email, "Password reset", f"Use this link within 1 hour to reset your password:\n{link}")
    return {"message": "If that e-mail is registered and e-mail delivery is configured, a reset link has been sent. "
                       "Otherwise, ask the administrator to issue a reset token."}


@router.post("/password-reset/confirm")
def reset_confirm(data: ResetConfirmIn, db: Session = Depends(get_db)):
    tok = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_reset_token(data.token)))
    if not tok or tok.used_at or tok.expires_at < utcnow():
        raise HTTPException(400, "This reset link is invalid or has expired.")
    user = db.get(User, tok.user_id)
    user.password_hash = hash_password(data.new_password)
    user.token_version += 1
    tok.used_at = utcnow()
    audit(db, user.id, "auth.password_reset", "user", user.id)
    db.commit()
    return {"message": "Password updated. You can now sign in."}
