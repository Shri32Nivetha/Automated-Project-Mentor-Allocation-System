"""Hierarchical domain matching between a team and a faculty member (pure functions, no database access).

TIERS (explicit hierarchy used by the optimiser; lower number = better)
  1  PRIMARY     the team's *primary* project domain is one of the faculty member's expertise / supported domains.
  2  ADDITIONAL  no primary match, but at least one of the team's *additional* domains is an exact expertise /
                 supported match. Matching several additional domains ranks higher (see ``exact_count``).
  3  RELATED     no exact match at all, but a team domain is the direct parent or child (``Domain.parent_id``) of an
                 expertise / supported domain. Reported as "related", never as an exact match.
  -  NONE        otherwise. The faculty member is NOT compatible: the optimiser never assigns them automatically; only
                 an administrator can do it through the explicit override workflow.

A faculty member who merely lists a domain as an *interest* is not compatible by that alone (interest still adds to the
secondary preference score used for tie-breaking).

PREFERENCE SCORE (secondary, used only after the hard priorities - see optimizer.py)
  A. primary domain vs faculty domains (best tier)       expertise 50 | supported 35 | related 20 | interest 15
  B. each additional domain (best tier), capped at 30    expertise 10 | supported 7  | related 2  | interest 3
  C. same department                                     +10  (a *hard* requirement when the department
                                                              restriction setting is on)
Workload fairness is NOT part of this score any more: it is handled globally by the optimiser.
"""
from dataclasses import dataclass, field

TIER_PRIMARY, TIER_ADDITIONAL, TIER_RELATED = 1, 2, 3
TIER_NAMES = {TIER_PRIMARY: "primary", TIER_ADDITIONAL: "additional", TIER_RELATED: "related"}

W_PRIMARY = {"expertise": 50, "supported": 35, "related": 20, "interest": 15}
W_INTEREST = {"expertise": 10, "supported": 7, "related": 2, "interest": 3}
INTEREST_CAP = 30
DEPT_BONUS = 10


@dataclass
class FacView:
    id: int
    name: str
    department: str
    capacity: int
    assigned: int                          # current workload that stays fixed for this calculation
    status_problem: str | None             # approved / active / available problem (independent of capacity)
    expertise: set = field(default_factory=set)
    supported: set = field(default_factory=set)
    interest: set = field(default_factory=set)

    @property
    def remaining(self) -> int:
        return max(0, self.capacity - self.assigned)


@dataclass
class TeamView:
    id: int
    name: str
    title: str
    department: str
    primary: int | None
    interests: set


def _is_related(dom: int, other: int, parents: dict) -> bool:
    return parents.get(dom) == other or parents.get(other) == dom


def _best_kind(dom: int, fac: FacView, parents: dict) -> tuple[str | None, int | None]:
    """Best match of one team domain against the faculty member: (kind, faculty_domain_id)."""
    if dom in fac.expertise:
        return "expertise", dom
    if dom in fac.supported:
        return "supported", dom
    for f in sorted(fac.expertise | fac.supported):
        if _is_related(dom, f, parents):
            return "related", f
    if dom in fac.interest:
        return "interest", dom
    return None, None


def match_pair(team: TeamView, fac: FacView, parents: dict, names: dict, restrict_dept: bool) -> dict:
    """Classify one (team, faculty) pair. The result is deterministic and fully explainable."""
    matched: list[dict] = []          # exact + related matches that determine the tier
    notes: list[str] = []
    dname = lambda i: names.get(i, f"domain {i}")  # noqa: E731

    primary_pts = interest_pts = 0
    primary_exact = False
    primary_related = False
    if team.primary is not None:
        kind, via = _best_kind(team.primary, fac, parents)
        if kind:
            primary_pts = W_PRIMARY[kind]
        if kind in ("expertise", "supported"):
            primary_exact = True
            matched.append({"domain_id": team.primary, "domain": dname(team.primary), "role": "primary",
                            "match": "exact", "faculty_kind": kind, "via": dname(via)})
        elif kind == "related":
            primary_related = True
            matched.append({"domain_id": team.primary, "domain": dname(team.primary), "role": "primary",
                            "match": "related", "faculty_kind": kind, "via": dname(via)})
        elif kind == "interest":
            notes.append(f"faculty lists '{dname(team.primary)}' only as an interest (+{primary_pts}, not a domain match)")

    additional_exact = additional_related = 0
    for d in sorted(team.interests):
        kind, via = _best_kind(d, fac, parents)
        if kind:
            interest_pts += W_INTEREST[kind]
        if kind in ("expertise", "supported"):
            additional_exact += 1
            matched.append({"domain_id": d, "domain": dname(d), "role": "additional", "match": "exact",
                            "faculty_kind": kind, "via": dname(via)})
        elif kind == "related":
            additional_related += 1
            matched.append({"domain_id": d, "domain": dname(d), "role": "additional", "match": "related",
                            "faculty_kind": kind, "via": dname(via)})
    interest_pts = min(interest_pts, INTEREST_CAP)

    if primary_exact:
        tier = TIER_PRIMARY
    elif additional_exact:
        tier = TIER_ADDITIONAL
    elif primary_related or additional_related:
        tier = TIER_RELATED
    else:
        tier = None

    exact_count = (1 if primary_exact else 0) + additional_exact
    related_count = (1 if primary_related else 0) + additional_related

    same_dept = fac.department.strip().lower() == team.department.strip().lower()
    dept_pts = DEPT_BONUS if same_dept else 0
    domain_score = primary_pts + interest_pts
    dept_blocked = restrict_dept and not same_dept

    # ---- concise explanation ----
    if tier == TIER_PRIMARY:
        extra = [m["domain"] for m in matched if m["role"] == "additional" and m["match"] == "exact"]
        s = f"Primary match: team's primary domain '{dname(team.primary)}' is in the mentor's {matched[0]['faculty_kind']} domains"
        if extra:
            s += f"; also covers additional domain(s): {', '.join(extra)}"
        notes.insert(0, s)
    elif tier == TIER_ADDITIONAL:
        ex = [m["domain"] for m in matched if m["role"] == "additional" and m["match"] == "exact"]
        notes.insert(0, "Additional-domain match: " + ", ".join(ex) +
                     (f" (primary domain '{dname(team.primary)}' is not covered by this mentor)" if team.primary else ""))
    elif tier == TIER_RELATED:
        rel = [f"'{m['domain']}' ~ '{m['via']}'" for m in matched if m["match"] == "related"]
        notes.insert(0, "Related-domain match (parent/child, not exact): " + ", ".join(rel))
    else:
        notes.insert(0, "No compatible domain match")
    if same_dept:
        notes.append(f"same department (+{DEPT_BONUS})")
    return {"tier": tier, "tier_name": TIER_NAMES.get(tier), "matched": matched, "exact_count": exact_count,
            "related_count": related_count, "domain_score": domain_score, "dept_blocked": dept_blocked,
            "same_department": same_dept, "compatible": tier is not None and not dept_blocked,
            "domain_compatible": tier is not None, "total": round(domain_score + dept_pts, 2), "notes": notes}


def score_pair(team: TeamView, fac: FacView, parents: dict, restrict_dept: bool, names: dict | None = None) -> dict:
    """Backwards-compatible alias of :func:`match_pair` (``names`` is only used for readable explanations)."""
    return match_pair(team, fac, parents, names or {}, restrict_dept)
