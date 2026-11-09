"""Create an administrator account from the command line (the ONLY way to create an admin).

    python -m scripts.create_admin --email admin@college.edu --name "Admin Name"

The password is requested interactively (hidden). For automation you may set ADMIN_PASSWORD in
the environment instead. There is no default admin and no public admin-registration page.
"""
import argparse
import getpass
import os
import sys

from sqlalchemy import select

from app.database import SessionLocal
from app.models import ROLE_ADMIN, User
from app.security import hash_password, validate_password_strength
from app.services.common import audit, norm_email


def create_admin(db, email: str, name: str, password: str) -> User:
    email = norm_email(email)
    if "@" not in email:
        raise ValueError("Enter a valid e-mail address.")
    validate_password_strength(password)
    if db.scalar(select(User).where(User.email == email)):
        raise ValueError(f"A user with e-mail {email} already exists.")
    u = User(email=email, full_name=name.strip(), role=ROLE_ADMIN, password_hash=hash_password(password))
    db.add(u)
    db.flush()
    audit(db, None, "admin.bootstrap", "user", u.id, {"email": email})
    db.commit()
    return u


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email", required=True)
    ap.add_argument("--name", required=True)
    a = ap.parse_args()
    pw = os.environ.get("ADMIN_PASSWORD")
    if not pw:
        pw = getpass.getpass("Admin password (min 8 chars, letters + numbers): ")
        if pw != getpass.getpass("Repeat password: "):
            sys.exit("Passwords do not match.")
    try:
        with SessionLocal() as db:
            u = create_admin(db, a.email, a.name, pw)
    except ValueError as e:
        sys.exit(f"Error: {e}")
    print(f"Admin created: {u.email}")


if __name__ == "__main__":
    main()
