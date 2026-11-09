"""Relational schema (SQLAlchemy 2.x declarative, MySQL / utf8mb4).

Key integrity rules enforced by the database itself:
  * users.email, faculty_profiles.employee_id unique
  * team_members: unique (cycle_id, registration_number) and unique (cycle_id, email)
    -> a student can be in only one team per allocation cycle
  * allocations: unique (cycle_id, team_id) -> one guide per team per cycle
  * allocation_cycles.active_marker unique -> at most one active cycle
"""
from datetime import date, datetime

from sqlalchemy import (JSON, Boolean, Date, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base, UTCDateTime, utcnow

TA = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci", "mysql_engine": "InnoDB"}

# ---- enumerations (stored as short strings, validated in services/schemas) ----
ROLE_ADMIN, ROLE_FACULTY, ROLE_LEADER = "admin", "faculty", "team_leader"
ROLES = (ROLE_ADMIN, ROLE_FACULTY, ROLE_LEADER)
FAC_PENDING, FAC_APPROVED, FAC_REJECTED = "pending", "approved", "rejected"
P_DRAFT, P_SUBMITTED, P_REVIEW, P_APPROVED = "draft", "submitted", "under_review", "approved"
P_REVISION, P_REJECTED, P_ALLOCATED, P_FINALISED = "needs_revision", "rejected", "allocated", "finalised"
PROPOSAL_STATUSES = (P_DRAFT, P_SUBMITTED, P_REVIEW, P_APPROVED, P_REVISION, P_REJECTED, P_ALLOCATED, P_FINALISED)
A_ALLOCATED, A_FINALISED = "allocated", "finalised"
CYCLE_PLANNED, CYCLE_ACTIVE, CYCLE_FINALISED, CYCLE_ARCHIVED = "planned", "active", "finalised", "archived"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (TA,)
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(190), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(150))
    role: Mapped[str] = mapped_column(String(20), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)  # bump to invalidate old JWTs
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (TA,)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class SystemSetting(Base):
    __tablename__ = "system_settings"
    __table_args__ = (TA,)
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict | list | str | int | bool | None] = mapped_column(JSON)
    description: Mapped[str] = mapped_column(String(300), default="")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class AllocationCycle(Base):
    __tablename__ = "allocation_cycles"
    __table_args__ = (TA,)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    academic_year: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default=CYCLE_PLANNED, index=True)
    active_marker: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)  # 1 when active
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    registration_deadline: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    proposal_deadline: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finalised_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    @property
    def is_active(self) -> bool:
        return self.active_marker == 1


class Domain(Base):
    __tablename__ = "domains"
    __table_args__ = (TA,)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    description: Mapped[str] = mapped_column(String(300), default="")
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("domains.id", ondelete="SET NULL"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_other: Mapped[bool] = mapped_column(Boolean, default=False)   # the explicit "Other" entry
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)  # typed in by a user via "Other"
    custom_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # pending/approved/rejected
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class FacultyProfile(Base):
    __tablename__ = "faculty_profiles"
    __table_args__ = (TA,)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    employee_id: Mapped[str] = mapped_column(String(60), unique=True)
    department: Mapped[str] = mapped_column(String(120), index=True)
    designation: Mapped[str] = mapped_column(String(80))
    approval_status: Mapped[str] = mapped_column(String(20), default=FAC_PENDING, index=True)
    approval_remarks: Mapped[str] = mapped_column(String(500), default="")
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    max_capacity: Mapped[int] = mapped_column(Integer, default=0)  # default capacity; per-cycle rows override
    additional_interests: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    user: Mapped[User] = relationship(lazy="joined")
    domains: Mapped[list["FacultyDomain"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class FacultyDomain(Base):
    __tablename__ = "faculty_domains"
    __table_args__ = (UniqueConstraint("faculty_id", "domain_id", "kind", name="uq_faculty_domain_kind"), TA)
    id: Mapped[int] = mapped_column(primary_key=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty_profiles.id", ondelete="CASCADE"), index=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"), index=True)
    kind: Mapped[str] = mapped_column(String(12))  # expertise | supported | interest
    domain: Mapped[Domain] = relationship(lazy="joined")


class FacultyCycleCapacity(Base):
    """Capacity (in team projects) of a faculty member within one allocation cycle."""
    __tablename__ = "faculty_cycle_capacity"
    __table_args__ = (UniqueConstraint("faculty_id", "cycle_id", name="uq_faculty_cycle_capacity"), TA)
    id: Mapped[int] = mapped_column(primary_key=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty_profiles.id", ondelete="CASCADE"), index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("allocation_cycles.id"), index=True)
    max_capacity: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class CapacityChange(Base):
    __tablename__ = "capacity_changes"
    __table_args__ = (TA,)
    id: Mapped[int] = mapped_column(primary_key=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty_profiles.id", ondelete="CASCADE"), index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("allocation_cycles.id"))
    old_capacity: Mapped[int] = mapped_column(Integer)
    new_capacity: Mapped[int] = mapped_column(Integer)
    assigned_at_change: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(String(500))
    changed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("cycle_id", "name", name="uq_team_cycle_name"),
                      UniqueConstraint("cycle_id", "leader_user_id", name="uq_team_cycle_leader"), TA)
    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("allocation_cycles.id"), index=True)
    leader_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    department: Mapped[str] = mapped_column(String(120), index=True)
    programme: Mapped[str] = mapped_column(String(120))
    year_semester: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    leader: Mapped[User] = relationship(lazy="joined")
    cycle: Mapped[AllocationCycle] = relationship(lazy="joined")
    members: Mapped[list["TeamMember"]] = relationship(cascade="all, delete-orphan", lazy="selectin",
                                                        order_by="TeamMember.id")
    domains: Mapped[list["TeamDomain"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    proposal: Mapped["Proposal | None"] = relationship(uselist=False, cascade="all, delete-orphan", lazy="selectin")
    allocation: Mapped["Allocation | None"] = relationship(uselist=False, lazy="selectin")


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("cycle_id", "registration_number", name="uq_member_cycle_regno"),
                      UniqueConstraint("cycle_id", "email", name="uq_member_cycle_email"), TA)
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("allocation_cycles.id"))  # denormalised for the unique keys
    full_name: Mapped[str] = mapped_column(String(150))
    email: Mapped[str] = mapped_column(String(190))
    registration_number: Mapped[str] = mapped_column(String(60))
    department: Mapped[str] = mapped_column(String(120))
    programme: Mapped[str] = mapped_column(String(120))
    year_semester: Mapped[str] = mapped_column(String(40), default="")
    is_leader: Mapped[bool] = mapped_column(Boolean, default=False)


class TeamDomain(Base):
    __tablename__ = "team_domains"
    __table_args__ = (UniqueConstraint("team_id", "domain_id", name="uq_team_domain"), TA)
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # primary | interest
    domain: Mapped[Domain] = relationship(lazy="joined")


class Proposal(Base):
    __tablename__ = "proposals"
    __table_args__ = (TA,)
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), unique=True)
    title: Mapped[str] = mapped_column(String(250), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    technologies: Mapped[list] = mapped_column(JSON, default=list)
    objectives: Mapped[str] = mapped_column(Text, default="")
    expected_outcomes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default=P_DRAFT, index=True)
    eligible_for_allocation: Mapped[bool] = mapped_column(Boolean, default=False)
    admin_remarks: Mapped[str] = mapped_column(Text, default="")
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    reviews: Mapped[list["ProposalReview"]] = relationship(cascade="all, delete-orphan", lazy="select",
                                                            order_by="ProposalReview.id")


class ProposalReview(Base):
    __tablename__ = "proposal_reviews"
    __table_args__ = (TA,)
    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id", ondelete="CASCADE"), index=True)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    from_status: Mapped[str] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    remarks: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class TeamChangeRequest(Base):
    """Leader's request to change membership after allocation finalisation (admin must approve)."""
    __tablename__ = "team_change_requests"
    __table_args__ = (TA,)
    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(15), default="pending", index=True)  # pending/approved/rejected
    admin_remarks: Mapped[str] = mapped_column(Text, default="")
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Allocation(Base):
    __tablename__ = "allocations"
    __table_args__ = (UniqueConstraint("cycle_id", "team_id", name="uq_allocation_cycle_team"),
                      Index("ix_alloc_cycle_faculty", "cycle_id", "faculty_id"), TA)
    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("allocation_cycles.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculty_profiles.id"))
    status: Mapped[str] = mapped_column(String(15), default=A_ALLOCATED)
    method: Mapped[str] = mapped_column(String(10), default="auto")  # auto | manual
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    explanation: Mapped[str] = mapped_column(Text, default="")
    assigned_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finalised_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # --- optimiser / override audit (migration 0002) ---
    match_tier: Mapped[str | None] = mapped_column(String(12), nullable=True)   # primary | additional | related | override
    matched_domains: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_override: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")  # admin exception to domain compatibility
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_recommendation: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # what the optimiser originally recommended
    faculty: Mapped[FacultyProfile] = relationship(lazy="joined")


class AllocationHistory(Base):
    __tablename__ = "allocation_history"
    __table_args__ = (TA,)
    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("allocation_cycles.id"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    action: Mapped[str] = mapped_column(String(30))  # auto_assign/manual_assign/reassign/unassign/finalise
    old_faculty_id: Mapped[int | None] = mapped_column(ForeignKey("faculty_profiles.id"), nullable=True)
    new_faculty_id: Mapped[int | None] = mapped_column(ForeignKey("faculty_profiles.id"), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    performed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # --- override audit (migration 0002) ---
    is_override: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    domain_violation: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")    # no compatible domain
    capacity_violation: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")  # exceeded nominal capacity
    projected_load: Mapped[int | None] = mapped_column(Integer, nullable=True)   # new mentor's load after this change
    capacity_at_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)            # tier, matched domains, auto recommendation


class AllocationPreview(Base):
    __tablename__ = "allocation_previews"
    __table_args__ = (TA,)
    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[int] = mapped_column(ForeignKey("allocation_cycles.id"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(15), default="pending")  # pending/committed/discarded
    payload: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    committed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notif_user_read", "user_id", "is_read"), TA)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(40), default="info")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (TA,)
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    actor: Mapped[User | None] = relationship(lazy="joined")
