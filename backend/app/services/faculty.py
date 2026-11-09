"""Faculty registration, approval and profile management."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (FAC_APPROVED, FAC_PENDING, FAC_REJECTED, ROLE_FACULTY, CapacityChange, Domain, FacultyCycleCapacity,
                      FacultyDomain, FacultyProfile, User)
from ..schemas import FacultyRegisterIn
from ..security import hash_password
from . import workload
from .common import active_cycle, audit, check_institutional_email, get_setting, norm_email, norm_name, notify
from .domains import resolve_domains


def set_faculty_domains(db: Session, prof: FacultyProfile, expertise, supported, interest, custom_name, user_id):
    """Replace domain relationships. 'Other' + custom_name is expanded once and applied to every list that chose Other."""
    groups = {"expertise": expertise, "supported": supported, "interest": interest}
    if all(v is None for v in groups.values()):
        return
    existing = {k: [fd.domain_id for fd in prof.domains if fd.kind == k] for k in groups}
    for k, v in groups.items():
        if v is None:
            groups[k] = existing[k]
    other = db.scalar(select(Domain).where(Domain.is_other == True))  # noqa: E712
    other_id = other.id if other else None
    any_other = any(other_id in ids for ids in groups.values())
    if custom_name and custom_name.strip() and not any_other:
        raise HTTPException(422, "A custom domain name was given but 'Other' was not selected.")
    resolved = {}
    for k, ids in groups.items():
        use_custom = custom_name if other_id in ids else None
        doms, _ = resolve_domains(db, ids, use_custom, user_id) if ids else ([], None)
        resolved[k] = doms
    # Allow custom name once when Other was selected in any group (already created by the first call).
    prof.domains.clear()
    db.flush()
    for k, doms in resolved.items():
        for d in doms:
            prof.domains.append(FacultyDomain(domain_id=d.id, kind=k, domain=d))


def register_faculty(db: Session, data: FacultyRegisterIn) -> FacultyProfile:
    email = check_institutional_email(data.email)      # normalised, @srmist.edu.in only
    emp = data.employee_id.strip().upper()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "This e-mail address is already registered.")
    if db.scalar(select(FacultyProfile.id).where(FacultyProfile.employee_id == emp)):
        raise HTTPException(409, "This employee ID is already registered.")
    try:
        user = User(email=email, full_name=norm_name(data.full_name), role=ROLE_FACULTY,
                    password_hash=hash_password(data.password), is_active=True)
        db.add(user)
        db.flush()
        prof = FacultyProfile(user_id=user.id, employee_id=emp, department=norm_name(data.department),
                              designation=norm_name(data.designation), approval_status=FAC_PENDING,
                              is_available=data.is_available, max_capacity=data.requested_capacity,
                              additional_interests=data.additional_interests.strip())
        db.add(prof)
        db.flush()
        prof.domains = []
        # an "Other" custom name applies to whichever list selected Other
        set_faculty_domains(db, prof, data.expertise_domain_ids, data.supported_domain_ids,
                            data.interest_domain_ids, data.custom_domain_name, user.id)
        notify(db, user.id, "Registration received", "Your faculty registration is pending administrator approval. "
                                                     "You will not receive project teams until approved.", "faculty_pending")
        audit(db, user.id, "faculty.register", "faculty", prof.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "E-mail or employee ID is already registered.")
    except HTTPException:
        db.rollback()
        raise
    return prof


def decide_faculty(db: Session, prof: FacultyProfile, admin_id: int, approve: bool, remarks: str, capacity: int | None) -> dict:
    """Approve (capacity REQUIRED and validated) or reject a registration, in one transaction.

    The saved capacity is written to the faculty profile (the default for every cycle) and, when a cycle is active,
    to that cycle's capacity row, which is exactly what the allocation engine reads. It is also logged in capacity_changes.
    """
    # serialise with concurrent approvals / capacity edits / allocation runs touching this faculty member
    db.execute(select(FacultyProfile.id).where(FacultyProfile.id == prof.id).with_for_update())
    db.refresh(prof)
    result: dict = {}
    if approve:
        if prof.approval_status == FAC_APPROVED:
            raise HTTPException(409, "This faculty member is already approved. Change the capacity from the workload "
                                     "or faculty detail screen instead.")
        cap = workload.validate_capacity(db, capacity, "capacity")
        cyc = active_cycle(db, required=False)
        old = workload.effective_capacity(db, prof, cyc.id) if cyc else prof.max_capacity
        prof.approval_status = FAC_APPROVED
        prof.max_capacity = cap
        if cyc:
            row = db.scalar(select(FacultyCycleCapacity).where(FacultyCycleCapacity.faculty_id == prof.id,
                                                               FacultyCycleCapacity.cycle_id == cyc.id))
            if row is None:
                db.add(FacultyCycleCapacity(faculty_id=prof.id, cycle_id=cyc.id, max_capacity=cap))
            else:
                row.max_capacity = cap
            db.add(CapacityChange(faculty_id=prof.id, cycle_id=cyc.id, old_capacity=old, new_capacity=cap,
                                  assigned_at_change=workload.assigned_counts(db, cyc.id).get(prof.id, 0),
                                  reason="Capacity set at approval", changed_by=admin_id))
        result = {"capacity": cap, "cycle": cyc.name if cyc else None}
    else:
        prof.approval_status = FAC_REJECTED
    prof.approval_remarks = remarks
    notify(db, prof.user_id, "Registration " + ("approved" if approve else "rejected"),
           (f"Your faculty registration was approved with a project capacity of {result['capacity']} team(s). "
            "You may now be assigned project teams." if approve else f"Your faculty registration was rejected. {remarks}"),
           "faculty_decision")
    audit(db, admin_id, "faculty.approve" if approve else "faculty.reject", "faculty", prof.id,
          {"remarks": remarks, **({"capacity": result["capacity"]} if approve else {})})
    db.commit()
    return result


def serialize_faculty_domains(prof: FacultyProfile) -> dict:
    out = {"expertise": [], "supported": [], "interest": []}
    for fd in prof.domains:
        out[fd.kind].append({"id": fd.domain.id, "name": fd.domain.name, "is_custom": fd.domain.is_custom,
                             "custom_status": fd.domain.custom_status})
    return out
