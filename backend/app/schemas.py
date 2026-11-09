"""Pydantic request/response schemas. Requests never accept role, status or capacity fields
that a caller is not entitled to set (protection against mass assignment: extra fields are forbidden)."""
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from .security import validate_password_strength
from .services.common import validate_regno


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth ----------
class LoginIn(In):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class PasswordChangeIn(In):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _pw(cls, v):
        return validate_password_strength(v)


class ResetRequestIn(In):
    email: EmailStr


class ResetConfirmIn(In):
    token: str = Field(min_length=10, max_length=200)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _pw(cls, v):
        return validate_password_strength(v)


class UserOut(Out):
    id: int
    email: EmailStr
    full_name: str
    role: str
    is_active: bool


# ---------- domains ----------
class DomainOut(Out):
    id: int
    name: str
    description: str
    parent_id: int | None
    is_active: bool
    is_other: bool
    is_custom: bool
    custom_status: str | None


class DomainIn(In):
    name: str = Field(min_length=2, max_length=150)
    description: str = Field(default="", max_length=300)
    parent_id: int | None = None


class DomainUpdate(In):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = Field(default=None, max_length=300)
    parent_id: int | None = None
    is_active: bool | None = None
    clear_parent: bool = False


class CustomDomainReview(In):
    action: Literal["approve", "reject", "map"]
    map_to_domain_id: int | None = None


# ---------- cycles ----------
class CycleIn(In):
    name: str = Field(min_length=2, max_length=100)
    academic_year: str = Field(min_length=4, max_length=20)
    start_date: date | None = None
    end_date: date | None = None
    registration_deadline: datetime | None = None
    proposal_deadline: datetime | None = None


class CycleUpdate(In):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    academic_year: str | None = Field(default=None, min_length=4, max_length=20)
    start_date: date | None = None
    end_date: date | None = None
    registration_deadline: datetime | None = None
    proposal_deadline: datetime | None = None
    status: Literal["planned", "archived"] | None = None


class CycleOut(Out):
    id: int
    name: str
    academic_year: str
    status: str
    is_active: bool
    start_date: date | None
    end_date: date | None
    registration_deadline: datetime | None
    proposal_deadline: datetime | None
    finalised_at: datetime | None


# ---------- team registration ----------
class MemberIn(In):
    full_name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    registration_number: str = Field(min_length=2, max_length=60)
    department: str | None = Field(default=None, max_length=120)
    programme: str | None = Field(default=None, max_length=120)
    year_semester: str | None = Field(default=None, max_length=40)

    @field_validator("registration_number")
    @classmethod
    def _regno(cls, v):
        return validate_regno(v)


class LeaderIn(MemberIn):
    password: str
    department: str = Field(min_length=2, max_length=120)
    programme: str = Field(min_length=2, max_length=120)

    @field_validator("password")
    @classmethod
    def _pw(cls, v):
        return validate_password_strength(v)


class TeamRegisterIn(In):
    team_name: str = Field(min_length=2, max_length=120)
    department: str = Field(min_length=2, max_length=120)
    programme: str = Field(min_length=2, max_length=120)
    year_semester: str = Field(default="", max_length=40)
    cycle_id: int | None = None  # optional; must equal the active cycle if supplied
    number_of_members: int = Field(ge=1, le=50)
    leader: LeaderIn
    members: list[MemberIn] = Field(default_factory=list, max_length=49)

    @model_validator(mode="after")
    def _count(self):
        if self.number_of_members != len(self.members) + 1:
            raise ValueError("number_of_members must equal the leader plus the listed members.")
        return self


class TeamUpdateIn(In):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    department: str | None = Field(default=None, min_length=2, max_length=120)
    programme: str | None = Field(default=None, min_length=2, max_length=120)
    year_semester: str | None = Field(default=None, max_length=40)


class MemberUpdateIn(In):
    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    email: EmailStr | None = None
    registration_number: str | None = Field(default=None, min_length=2, max_length=60)
    department: str | None = Field(default=None, max_length=120)
    programme: str | None = Field(default=None, max_length=120)
    year_semester: str | None = Field(default=None, max_length=40)


class MemberOut(Out):
    id: int
    full_name: str
    email: str
    registration_number: str
    department: str
    programme: str
    year_semester: str
    is_leader: bool


class ChangeRequestIn(In):
    description: str = Field(min_length=10, max_length=2000)


class ChangeRequestResolve(In):
    action: Literal["approve", "reject"]
    remarks: str = Field(default="", max_length=1000)


# ---------- proposals ----------
class ProposalIn(In):
    title: str = Field(default="", max_length=250)
    description: str = Field(default="", max_length=10000)
    primary_domain_id: int | None = None
    interest_domain_ids: list[int] = Field(default_factory=list, max_length=15)
    custom_domain_name: str | None = Field(default=None, max_length=150)
    technologies: list[str] = Field(default_factory=list, max_length=30)
    objectives: str = Field(default="", max_length=5000)
    expected_outcomes: str = Field(default="", max_length=5000)

    @field_validator("technologies")
    @classmethod
    def _tech(cls, v):
        return [t.strip()[:60] for t in v if t and t.strip()]


class ReviewIn(In):
    action: Literal["start_review", "approve", "request_revision", "reject", "set_eligibility"]
    remarks: str = Field(default="", max_length=2000)
    eligible: bool | None = None

    @model_validator(mode="after")
    def _need_remarks(self):
        if self.action in ("request_revision", "reject") and len(self.remarks.strip()) < 3:
            raise ValueError("Remarks are required when requesting a revision or rejecting a proposal.")
        if self.action == "set_eligibility" and self.eligible is None:
            raise ValueError("'eligible' is required for set_eligibility.")
        return self


# ---------- faculty ----------
class FacultyRegisterIn(In):
    full_name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    employee_id: str = Field(min_length=1, max_length=60)
    department: str = Field(min_length=2, max_length=120)
    designation: str = Field(min_length=2, max_length=80)
    password: str
    expertise_domain_ids: list[int] = Field(min_length=1, max_length=30)
    supported_domain_ids: list[int] = Field(default_factory=list, max_length=30)
    interest_domain_ids: list[int] = Field(default_factory=list, max_length=30)
    custom_domain_name: str | None = Field(default=None, max_length=150)
    additional_interests: str = Field(default="", max_length=500)
    is_available: bool = True
    requested_capacity: int = Field(ge=1, le=100)

    @field_validator("password")
    @classmethod
    def _pw(cls, v):
        return validate_password_strength(v)


class FacultyProfileUpdateIn(In):
    """What a faculty member may change about themselves. No capacity / approval fields."""
    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    department: str | None = Field(default=None, min_length=2, max_length=120)
    expertise_domain_ids: list[int] | None = Field(default=None, min_length=1, max_length=30)
    supported_domain_ids: list[int] | None = Field(default=None, max_length=30)
    interest_domain_ids: list[int] | None = Field(default=None, max_length=30)
    custom_domain_name: str | None = Field(default=None, max_length=150)
    additional_interests: str | None = Field(default=None, max_length=500)
    is_available: bool | None = None


class AdminFacultyUpdateIn(FacultyProfileUpdateIn):
    employee_id: str | None = Field(default=None, min_length=1, max_length=60)
    designation: str | None = Field(default=None, min_length=2, max_length=80)


class FacultyDecisionIn(In):
    """Rejection: remarks only."""
    remarks: str = Field(default="", max_length=500)


class FacultyApproveIn(In):
    """Approval. ``capacity`` is REQUIRED and validated in one place (services.workload.validate_capacity) against the
    configured min/max, so a decimal, text, negative or out-of-range value gets a clear field-level 422."""
    remarks: str = Field(default="", max_length=500)
    capacity: Any = None


class CapacityIn(In):
    max_capacity: Any = None                       # validated by services.workload.validate_capacity
    reason: str = Field(min_length=3, max_length=500)
    confirm_below_assigned: bool = False
    cycle_id: int | None = None
    expected_capacity: int | None = None           # optimistic-concurrency token: capacity the admin saw


# ---------- allocation ----------
class PreviewIn(In):
    cycle_id: int | None = None
    # By default only teams without a guide are optimised and every existing assignment (automatic or manual) is kept.
    reoptimize: bool = False            # also re-decide existing AUTOMATIC assignments that are not finalised
    include_manual: bool = False        # additionally re-decide MANUAL assignments (explicit administrator choice)


class CommitIn(In):
    confirm: bool = False
    acknowledge_overload: bool = False  # required when the previewed plan exceeds some mentor's nominal capacity


class ManualIn(In):
    team_id: int
    faculty_id: int
    reason: str = Field(default="", max_length=500)
    confirm: bool = False
    override_domain: bool = False       # explicit administrator exception: no compatible domain
    acknowledge_overload: bool = False  # explicit administrator exception: exceeds nominal capacity


class UnassignIn(In):
    team_id: int
    reason: str = Field(min_length=3, max_length=500)
    confirm: bool = False


class FinaliseIn(In):
    confirm: bool = False
    cycle_id: int | None = None
    acknowledge_overload: bool = False


class SettingsIn(In):
    values: dict[str, object]
