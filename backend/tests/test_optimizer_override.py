"""Global optimiser, hierarchical matching, administrator override, re-optimisation and failure handling."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import app
from app.models import Allocation, AllocationHistory, AllocationPreview
from app.services import optimizer
from tests.helpers import API, admin_headers, approved_team, make_faculty, new_cycle, preview_and_commit

CY, IOT, ROB, ML, AI = "Cybersecurity", "Internet of Things", "Robotics", "Machine Learning", "Artificial Intelligence"


@pytest.fixture
def ah(client):
    h = admin_headers(client)
    new_cycle(client, h)
    return h


def preview(client, ah, **opts):
    r = client.post(f"{API}/admin/allocation/preview", headers=ah, json=opts)
    assert r.status_code == 201, r.text
    return r.json()


def by_team(pv):
    return {a["team_id"]: a for a in pv["assignments"]}


def manual(client, ah, team, fac, **kw):
    return client.post(f"{API}/admin/allocation/manual", headers=ah,
                       json={"team_id": team["id"], "faculty_id": fac["id"], "confirm": True, **kw})


# ---------------------------------------------------------------- hierarchical matching
def test_primary_match_is_preferred_over_additional(client, ah):
    prim = make_faculty(client, ah, "Primary", [CY], cap=5)
    make_faculty(client, ah, "Extra", [IOT], cap=50)               # far more spare capacity, but only an additional match
    t = approved_team(client, ah, CY, interests=[IOT])
    a = by_team(preview(client, ah))[t["id"]]
    assert a["faculty_id"] == prim["id"] and a["tier"] == "primary"
    assert a["matched_domains"][0]["role"] == "primary" and a["matched_domains"][0]["match"] == "exact"


def test_additional_domains_are_used_when_no_primary_mentor_exists(client, ah):
    f = make_faculty(client, ah, "IotProf", [IOT], cap=3)
    t = approved_team(client, ah, ROB, interests=[IOT])
    a = by_team(preview(client, ah))[t["id"]]
    assert a["faculty_id"] == f["id"] and a["tier"] == "additional" and "Additional-domain" in a["explanation"]


def test_related_domain_is_labelled_related_not_exact(client, ah):
    f = make_faculty(client, ah, "AiProf", [AI], cap=3)             # Machine Learning is a child of AI
    t = approved_team(client, ah, ML)
    a = by_team(preview(client, ah))[t["id"]]
    assert a["faculty_id"] == f["id"] and a["tier"] == "related"
    assert a["matched_domains"][0]["match"] == "related" and "not exact" in a["explanation"]


def test_mentor_matching_more_domains_is_preferred(client, ah):
    make_faculty(client, ah, "One", [CY], cap=5)
    two = make_faculty(client, ah, "Three", [CY, IOT, ROB], cap=5)
    t = approved_team(client, ah, CY, interests=[IOT, ROB])
    assert by_team(preview(client, ah))[t["id"]]["faculty_id"] == two["id"]


def test_overload_avoided_by_using_an_alternative_tier_and_explained(client, ah):
    p = make_faculty(client, ah, "PrimaryFull", [CY], cap=1)
    alt = make_faculty(client, ah, "AltRoomy", [IOT], cap=5)
    t1 = approved_team(client, ah, CY, interests=[IOT])
    t2 = approved_team(client, ah, CY, interests=[IOT])
    pv = preview(client, ah)
    a = by_team(pv)
    assert {a[t1["id"]]["faculty_id"], a[t2["id"]]["faculty_id"]} == {p["id"], alt["id"]}
    alt_row = next(x for x in pv["assignments"] if x["faculty_id"] == alt["id"])
    assert alt_row["tier"] == "additional" and "capacity" in alt_row["alternative_reason"]
    assert pv["summary"]["total_overload"] == 0 and pv["summary"]["new_overload"] == 0
    assert pv["solver"]["stages"][0]["stage"] == "assigned"


def test_worst_overload_is_minimised_before_total_overload(client, ah):
    for n, c in (("AA", 1), ("BB", 1)):
        make_faculty(client, ah, n, [CY], cap=c)
    for _ in range(4):
        approved_team(client, ah, CY)
    pv = preview(client, ah)
    s = pv["summary"]
    assert len(pv["assignments"]) == 4 and s["max_overload"] == 1 and s["total_overload"] == 2
    loads = sorted(p["projected"] for p in pv["faculty_projection"])
    assert loads == [2, 2]                                          # 2/1 and 2/1, never 3/1 + 1/1


# ---------------------------------------------------------------- no incompatible automatic assignment
def test_incompatible_mentor_never_assigned_automatically_and_team_flagged(client, ah):
    f = make_faculty(client, ah, "Cyber", [CY], cap=5)
    ok = approved_team(client, ah, CY)
    bad = approved_team(client, ah, ROB)
    pv = preview(client, ah)
    assert list(by_team(pv)) == [ok["id"]]
    u = pv["unassigned"][0]
    assert u["team_id"] == bad["id"] and u["code"] == "no_compatible_domain" and u["suggestions"][0]["faculty_id"] == f["id"]
    r = client.post(f"{API}/admin/allocation/preview/{pv['id']}/commit", headers=ah, json={"confirm": True}).json()
    assert r["requires_resolution"] == 1 and r["all_teams_compatible"] is False and "administrative resolution" in r["message"]
    un = client.get(f"{API}/admin/allocation/unallocated", headers=ah).json()
    assert un[0]["requires_resolution"] is True


# ---------------------------------------------------------------- administrator override
def test_override_requires_flag_reason_and_is_fully_audited(client, ah, db):
    good = make_faculty(client, ah, "Good", [CY], cap=5)
    odd = make_faculty(client, ah, "Odd", [IOT], cap=5)
    t = approved_team(client, ah, CY)
    preview_and_commit(client, ah)                                   # auto-assigned to Good
    chk = client.get(f"{API}/admin/allocation/manual-preview", headers=ah, params={"team_id": t["id"], "faculty_id": odd["id"]}).json()
    assert chk["requires_domain_override"] and chk["domain_compatible"] is False and chk["can_assign"]
    assert chk["warnings"][0]["code"] == "no_domain_match" and chk["faculty_domains"]["expertise"] == [IOT]
    assert chk["team_domains"]["primary"] == CY
    r = manual(client, ah, t, odd, reason="x y z")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "domain_override_required"
    r = manual(client, ah, t, odd, override_domain=True, reason="")
    assert r.status_code == 422
    r = manual(client, ah, t, odd, override_domain=True, reason="Only supervisor with free time")
    assert r.status_code == 200 and r.json()["is_override"] is True
    h = db.scalars(select(AllocationHistory).where(AllocationHistory.team_id == t["id"]).order_by(AllocationHistory.id.desc())).first()
    assert (h.action, h.is_override, h.domain_violation, h.capacity_violation) == ("reassign", True, True, False)
    assert h.reason == "Only supervisor with free time" and h.old_faculty_id == good["id"] and h.new_faculty_id == odd["id"]
    assert h.performed_by and h.created_at and h.details["auto_recommendation"]["faculty_id"] == good["id"]
    al = db.scalar(select(Allocation))
    assert al.method == "manual" and al.match_tier == "override" and al.override_reason
    assert al.auto_recommendation["faculty_id"] == good["id"]       # the original recommendation is preserved
    audit = client.get(f"{API}/admin/audit-logs", headers=ah, params={"action": "allocation.reassign"}).json()
    assert audit["total"] == 1


def test_override_may_exceed_capacity_only_with_acknowledgement(client, ah, db):
    full = make_faculty(client, ah, "Full", [CY], cap=1)
    approved_team(client, ah, CY)
    preview_and_commit(client, ah)
    t2 = approved_team(client, ah, CY)
    r = manual(client, ah, t2, full)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "overload_ack_required"
    r = manual(client, ah, t2, full, acknowledge_overload=True, reason="Student request")
    assert r.status_code == 200
    h = db.scalars(select(AllocationHistory).order_by(AllocationHistory.id.desc())).first()
    assert h.capacity_violation and not h.domain_violation and h.projected_load == 2 and h.capacity_at_time == 1


def test_override_never_bypasses_mandatory_rules_or_authorization(client, ah):
    away = make_faculty(client, ah, "Away", [IOT], cap=5, available=False)
    ok = make_faculty(client, ah, "Okay", [CY], cap=5)
    t = approved_team(client, ah, CY)
    r = manual(client, ah, t, away, override_domain=True, reason="please do it", acknowledge_overload=True)
    assert r.status_code == 409 and "unavailable" in r.json()["detail"]
    for who in (ok, t):                                              # faculty and team leader are refused
        assert manual(client, who["headers"], t, ok).status_code == 403
        assert client.post(f"{API}/admin/allocation/preview", headers=who["headers"], json={}).status_code == 403


# ---------------------------------------------------------------- re-optimisation / manual protection
def test_manual_assignments_are_preserved_unless_explicitly_included(client, ah, db):
    a = make_faculty(client, ah, "AA", [CY], cap=5)
    b = make_faculty(client, ah, "BB", [CY], cap=5)
    t_auto, t_man = approved_team(client, ah, CY), approved_team(client, ah, CY)
    assert manual(client, ah, t_man, b).status_code == 200            # manual (compatible)
    preview_and_commit(client, ah)                                    # t_auto auto-assigned
    pv = preview(client, ah)
    assert pv["assignments"] == []                                    # default run changes nothing
    pv = preview(client, ah, reoptimize=True)
    assert t_man["id"] not in by_team(pv)                             # manual is protected during re-optimisation
    assert preview(client, ah, reoptimize=True, include_manual=True) and t_man["id"] in by_team(
        preview(client, ah, reoptimize=True, include_manual=True))
    assert client.post(f"{API}/admin/allocation/preview", headers=ah, json={"include_manual": True}).status_code == 422
    # existing load is not double counted: projected load == real number of teams
    pv = preview(client, ah, reoptimize=True, include_manual=True)
    assert sum(p["projected"] for p in pv["faculty_projection"]) == 2
    r = client.post(f"{API}/admin/allocation/preview/{pv['id']}/commit", headers=ah, json={"confirm": True}).json()
    assert db.scalar(select(func.count()).select_from(Allocation)) == 2
    assert len(r["assigned"]) == 0 and len(r["reassigned"]) + len(r["unchanged"]) == 2


def test_overload_commit_needs_acknowledgement_and_is_deterministic(client, ah, db):
    make_faculty(client, ah, "Solo", [CY], cap=1)
    for _ in range(3):
        approved_team(client, ah, CY)
    p1, p2 = preview(client, ah), preview(client, ah)
    pick = lambda pv: [(a["team_id"], a["faculty_id"], a["tier"]) for a in pv["assignments"]]
    assert pick(p1) == pick(p2) and p1["summary"]["new_overload"] == 2     # repeatable
    r = client.post(f"{API}/admin/allocation/preview/{p2['id']}/commit", headers=ah, json={"confirm": True})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "overload_ack_required"
    assert db.scalar(select(func.count()).select_from(Allocation)) == 0
    r = client.post(f"{API}/admin/allocation/preview/{p2['id']}/commit", headers=ah,
                    json={"confirm": True, "acknowledge_overload": True})
    assert r.status_code == 200 and r.json()["overloaded"][0]["overload"] == 2


def test_finalise_with_overload_needs_acknowledgement(client, ah):
    make_faculty(client, ah, "Solo", [CY], cap=1)
    for _ in range(2):
        approved_team(client, ah, CY)
    preview_and_commit(client, ah)
    r = client.post(f"{API}/admin/allocation/finalise", headers=ah, json={"confirm": True})
    assert r.status_code == 409 and r.json()["detail"]["acknowledgeable"] is True
    assert client.post(f"{API}/admin/allocation/finalise", headers=ah,
                       json={"confirm": True, "acknowledge_overload": True}).status_code == 200


# ---------------------------------------------------------------- solver failure handling
@pytest.mark.parametrize("code,status", [("timeout", 504), ("infeasible", 503), ("failed", 503)])
def test_solver_failures_are_reported_and_change_nothing(client, ah, db, monkeypatch, code, status):
    make_faculty(client, ah, "AA", [CY], cap=3)
    approved_team(client, ah, CY)

    def boom(*a, **k):
        raise optimizer.SolverError(code, "simulated solver problem")
    monkeypatch.setattr(optimizer, "solve", boom)
    r = client.post(f"{API}/admin/allocation/preview", headers=ah, json={})
    assert r.status_code == status and r.json()["detail"]["code"] == f"solver_{code}"
    assert "No allocation was changed" in r.json()["detail"]["message"]
    assert db.scalar(select(func.count()).select_from(AllocationPreview)) == 0
    assert db.scalar(select(func.count()).select_from(Allocation)) == 0


def test_unexpected_solver_exception_does_not_leak_internals(client, ah, monkeypatch):
    make_faculty(client, ah, "AA", [CY], cap=3)
    approved_team(client, ah, CY)
    monkeypatch.setattr(optimizer, "solve", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret internals")))
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post(f"{API}/admin/allocation/preview", headers=ah, json={})
    assert r.status_code == 500 and "secret" not in r.text


def test_real_solver_time_limit_returns_feasible_result():
    """A tiny budget must still return a valid, fully assigned plan (flagged as not proved optimal when cut short)."""
    edges = {(t, f): optimizer.Edge(1 + (t + f) % 3, 1, 0, 100 + t * f) for t in range(1, 61) for f in range(1, 16)}
    res = optimizer.solve(list(range(1, 61)), {f: 0 for f in range(1, 16)}, {f: 3 for f in range(1, 16)}, edges, time_limit=0.3)
    assert len(res.assignment) == 60 and all((t, f) in edges for t, f in res.assignment.items())
