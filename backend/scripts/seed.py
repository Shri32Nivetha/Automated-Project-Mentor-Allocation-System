"""Seed lookup data (domain catalogue + default system settings). SAFE TO RE-RUN.

Only inserts what is missing. Existing rows (including ones an admin renamed, re-parented or
deactivated) are never overwritten. Run after `alembic upgrade head`:
    python -m scripts.seed
"""
import sys

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Domain, SystemSetting
from app.seed_data import DOMAINS
from app.services.common import DEFAULT_SETTINGS


def seed(db) -> dict:
    added_domains = added_settings = 0
    existing = {n.lower(): d for n, d in ((d.name, d) for d in db.scalars(select(Domain)))}
    pending_parents = []
    for name, desc, parent in DOMAINS:
        if name.lower() in existing:
            continue
        d = Domain(name=name, description=desc, is_other=(name == "Other"), is_active=True)
        db.add(d)
        existing[name.lower()] = d
        added_domains += 1
        if parent:
            pending_parents.append((d, parent))
    db.flush()
    for d, parent in pending_parents:        # parents only set on freshly created rows
        p = existing.get(parent.lower())
        if p is not None:
            d.parent_id = p.id
    # the explicit "Other" entry must always exist exactly once
    if not db.scalar(select(func.count()).select_from(Domain).where(Domain.is_other == True)):  # noqa: E712
        o = existing.get("other")
        if o is not None:
            o.is_other = True
    for key, (value, desc) in DEFAULT_SETTINGS.items():
        if db.get(SystemSetting, key) is None:
            db.add(SystemSetting(key=key, value=value, description=desc))
            added_settings += 1
    db.commit()
    return {"domains_added": added_domains, "settings_added": added_settings,
            "domains_total": db.scalar(select(func.count()).select_from(Domain))}


if __name__ == "__main__":
    with SessionLocal() as session:
        result = seed(session)
    print(result)
    sys.exit(0)
