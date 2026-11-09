"""Domain catalogue helpers shared by team, proposal and faculty flows."""
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Domain
from .common import norm_name


def resolve_domains(db: Session, domain_ids: list[int], custom_name: str | None, user_id: int | None):
    """Validate IDs against the catalogue and expand the explicit "Other" choice.

    * duplicates are removed; unknown / inactive IDs are rejected (422)
    * choosing "Other" requires custom_name; the custom domain is stored (pending admin review)
      under "Other" and replaces the Other id in the returned list
    * a custom name that already exists in the catalogue simply reuses that domain
    Returns (list[Domain] in input order, custom Domain | None)
    """
    seen, ids = set(), []
    for i in domain_ids:
        if i not in seen:
            seen.add(i)
            ids.append(i)
    domains = {d.id: d for d in db.scalars(select(Domain).where(Domain.id.in_(ids)))} if ids else {}
    out, custom_domain = [], None
    custom_name = norm_name(custom_name) if custom_name else None
    for i in ids:
        d = domains.get(i)
        if d is None or not d.is_active:
            raise HTTPException(422, f"Domain id {i} is invalid or inactive.")
        if d.is_other:
            if not custom_name or len(custom_name) < 3:
                raise HTTPException(422, "Please enter your custom domain name (at least 3 characters) when selecting 'Other'.")
            existing = db.scalar(select(Domain).where(func.lower(Domain.name) == custom_name.lower()))
            if existing is None:
                existing = Domain(name=custom_name[:150], description="Custom domain submitted by a user",
                                  parent_id=d.id, is_custom=True, custom_status="pending", created_by_user_id=user_id)
                db.add(existing)
                db.flush()
            elif not existing.is_active:
                raise HTTPException(422, f"Domain '{existing.name}' is inactive; choose another name.")
            custom_domain = existing
            d = existing
        out.append(d)
    if custom_name and custom_domain is None:
        raise HTTPException(422, "A custom domain name was given but 'Other' was not selected.")
    # collapse duplicates that may have appeared after expansion
    uniq, seen2 = [], set()
    for d in out:
        if d.id not in seen2:
            seen2.add(d.id)
            uniq.append(d)
    return uniq, custom_domain
