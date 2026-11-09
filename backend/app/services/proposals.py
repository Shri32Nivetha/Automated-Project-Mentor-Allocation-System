"""Project proposal workflow: draft -> submitted -> under_review -> approved / needs_revision / rejected."""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..database import utcnow
from ..models import (P_ALLOCATED, P_APPROVED, P_DRAFT, P_FINALISED, P_REJECTED, P_REVIEW, P_REVISION, P_SUBMITTED,
                      Proposal, ProposalReview, Team, TeamDomain)
from ..schemas import ProposalIn, ReviewIn
from .common import audit, norm_name, notify
from .domains import resolve_domains
from .teams import assert_leader_can_edit


def _set_domains(db: Session, team: Team, data: ProposalIn, user_id: int) -> None:
    ids = ([data.primary_domain_id] if data.primary_domain_id else []) + list(data.interest_domain_ids)
    domains, _ = resolve_domains(db, ids, data.custom_domain_name, user_id)
    team.domains.clear()
    db.flush()
    for i, d in enumerate(domains):
        kind = "primary" if (i == 0 and data.primary_domain_id) else "interest"
        team.domains.append(TeamDomain(domain_id=d.id, kind=kind, domain=d))


def save_proposal(db: Session, team: Team, data: ProposalIn, user_id: int) -> Proposal:
    assert_leader_can_edit(team)
    p = team.proposal
    _set_domains(db, team, data, user_id)
    p.title, p.description = norm_name(data.title), data.description.strip()
    p.technologies, p.objectives = data.technologies, data.objectives.strip()
    p.expected_outcomes = data.expected_outcomes.strip()
    audit(db, user_id, "proposal.save", "proposal", p.id)
    db.commit()
    return p


def submit_proposal(db: Session, team: Team, user_id: int) -> Proposal:
    assert_leader_can_edit(team)
    p = team.proposal
    problems = []
    if len(p.title) < 5:
        problems.append("a project title (at least 5 characters)")
    if len(p.description) < 30:
        problems.append("a project description (at least 30 characters)")
    if not any(td.kind == "primary" for td in team.domains):
        problems.append("a primary domain")
    if problems:
        raise HTTPException(422, "Before submitting, please provide " + ", ".join(problems) + ".")
    prev = p.status
    p.status, p.submitted_at, p.eligible_for_allocation = P_SUBMITTED, utcnow(), False
    db.add(ProposalReview(proposal_id=p.id, reviewer_id=None, from_status=prev, to_status=P_SUBMITTED,
                          remarks="Submitted by team leader"))
    notify(db, user_id, "Proposal submitted", "Your proposal was submitted and is waiting for administrator review.",
           "proposal_submitted")
    audit(db, user_id, "proposal.submit", "proposal", p.id)
    db.commit()
    return p


def review_proposal(db: Session, p: Proposal, admin_id: int, data: ReviewIn) -> Proposal:
    team = db.get(Team, p.team_id)
    prev, act = p.status, data.action
    if p.status in (P_ALLOCATED, P_FINALISED) or team.allocation is not None:
        raise HTTPException(409, "This team already has a guide. Unassign the guide before changing the proposal review.")
    if p.status == P_DRAFT:
        raise HTTPException(409, "The proposal has not been submitted yet.")
    remarks = data.remarks.strip()
    if act == "start_review":
        if p.status != P_SUBMITTED:
            raise HTTPException(409, "Only submitted proposals can be moved to review.")
        p.status = P_REVIEW
        msg = "Your proposal is now under review."
    elif act == "approve":
        if p.status not in (P_SUBMITTED, P_REVIEW):
            raise HTTPException(409, f"A proposal in status '{p.status}' cannot be approved directly.")
        p.status, p.eligible_for_allocation = P_APPROVED, True
        msg = "Your proposal was approved and is eligible for guide allocation."
    elif act == "request_revision":
        if p.status not in (P_SUBMITTED, P_REVIEW, P_APPROVED):
            raise HTTPException(409, f"Cannot request a revision for a proposal in status '{p.status}'.")
        p.status, p.eligible_for_allocation = P_REVISION, False
        msg = f"Your proposal needs revision: {remarks}"
    elif act == "reject":
        if p.status not in (P_SUBMITTED, P_REVIEW, P_APPROVED):
            raise HTTPException(409, f"Cannot reject a proposal in status '{p.status}'.")
        p.status, p.eligible_for_allocation = P_REJECTED, False
        msg = f"Your proposal was rejected: {remarks}"
    else:  # set_eligibility
        if p.status != P_APPROVED:
            raise HTTPException(409, "Only approved proposals can be marked eligible / ineligible for allocation.")
        p.eligible_for_allocation = bool(data.eligible)
        msg = ("Your team is eligible for guide allocation." if data.eligible
               else "Your team was temporarily excluded from guide allocation.")
    if remarks:
        p.admin_remarks = remarks
    elif act in ("approve", "start_review"):
        p.admin_remarks = ""
    db.add(ProposalReview(proposal_id=p.id, reviewer_id=admin_id, from_status=prev, to_status=p.status,
                          remarks=remarks or f"[{act}]"))
    notify(db, team.leader_user_id, "Proposal update", msg, f"proposal_{p.status}")
    audit(db, admin_id, f"proposal.{act}", "proposal", p.id, {"from": prev, "to": p.status, "remarks": remarks})
    db.commit()
    return p
