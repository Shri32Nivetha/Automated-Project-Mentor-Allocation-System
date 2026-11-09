import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import app
from app.models import Allocation, AllocationHistory, AllocationPreview, CapacityChange
from app.services.allocation import FacView, TeamView, run_optimizer, score_pair
from tests.helpers import (API, admin_headers, approved_team, domain_ids, make_faculty, new_cycle, preview_and_commit)

CY, IOT, ML = "Cybersecurity", "Internet of Things", "Machine Learning"


@pytest.fixture
def ah(client):
    h = admin_headers(client)
    new_cycle(client, h)
    return h


def workload(client, ah):
    return client.get(f"{API}/admin/workload", headers=ah).json()


def counts(client, ah):
    return {f["name"]: (f["assigned"], f["max_capacity"]) for f in workload(client, ah)["faculty"]}


# ---------------- workload dashboard ----------------
def test_workload_baseline_and_capacity_shortage(client, ah):
    make_faculty(client, ah, "AA", [CY], cap=1)
    make_faculty(client, ah, "BB", [CY], cap=1)
    for i in range(3):
        approved_team(client, ah, CY)
    w = workload(client, ah)
    assert w["teams_requiring_guides"] == 3 and w["eligible_faculty"] == 2
    assert w["estimated_baseline"] == 1.5                      # 3 teams / 2 faculty
    assert w["total_capacity"] == 2 and w["available_capacity"] == 2
    assert w["capacity_shortage"] == 1 and w["capacity_surplus"] == 0


def test_large_shortage_example_100_teams_85_capacity():
    # POLICY CHANGE: 100 teams, total capacity 85 -> every team is allocated and the unavoidable overload (15) is
    # spread as evenly as possible (worst overload 1) instead of leaving 15 teams unallocated.
    facs = [FacView(i, f"F{i}", "CSE", 5, 0, None, expertise={1}) for i in range(1, 18)]
    teams = [TeamView(i, f"T{i}", "t", "CSE", 1, set()) for i in range(1, 101)]
    out = run_optimizer(teams, facs, {}, {1: "AI"}, False)
    assert len(out["assignments"]) == 100 and out["unassigned"] == []
    assert out["summary_run"]["total_overload"] == 15 and out["summary_run"]["max_overload"] == 1


def test_capacity_is_per_team_not_per_student(client, ah):
    make_faculty(client, ah, "Solo", [CY], cap=1)
    approved_team(client, ah, CY, size=4)
    approved_team(client, ah, CY, size=2)
    pv, r = preview_and_commit(client, ah)
    assert len(r.json()["assigned"]) == 2 and r.json()["unassigned"] == []        # controlled overload, nobody left out
    assert counts(client, ah)["Solo"] == (2, 1)
    assert pv["summary"]["total_overload"] == 1 and r.json()["overloaded"][0]["overload"] == 1


# ---------------- eligibility ----------------
def test_zero_capacity_inactive_unapproved_unavailable_excluded(client, ah):
    client.put(f"{API}/admin/settings", headers=ah, json={"values": {"min_faculty_capacity": 0}})   # allow 0 = "paused"
    zero = make_faculty(client, ah, "Zero", [CY], cap=1)
    client.put(f"{API}/admin/faculty/{zero['id']}/capacity", headers=ah, json={"max_capacity": 0, "reason": "paused"})
    pend = make_faculty(client, ah, "Pending", [CY], cap=3, approve=False)
    away = make_faculty(client, ah, "Away", [CY], cap=3, available=False)
    off = make_faculty(client, ah, "Off", [CY], cap=3)
    client.post(f"{API}/admin/faculty/{off['id']}/deactivate", headers=ah)
    make_faculty(client, ah, "Okay", [CY], cap=1)
    approved_team(client, ah, CY)
    approved_team(client, ah, CY)
    pv = client.post(f"{API}/admin/allocation/preview", headers=ah, json={}).json()
    # only "Okay" is eligible; both teams go to them (overload 1), nobody ineligible is used
    assert {a["faculty_name"] for a in pv["assignments"]} == {"Okay"} and len(pv["assignments"]) == 2
    rows = {f["name"]: f for f in workload(client, ah)["faculty"] if f["approval_status"] == "approved"}
    assert rows["Zero"]["ineligible_reason"] == "capacity is zero"
    assert rows["Away"]["ineligible_reason"] == "marked unavailable"
    assert rows["Off"]["ineligible_reason"] == "account is deactivated"


def test_domain_compatibility_and_unassigned_reason(client, ah):
    make_faculty(client, ah, "CyberProf", [CY], cap=5)
    make_faculty(client, ah, "IotProf", [IOT], cap=5)
    t_cy = approved_team(client, ah, CY)
    t_ml = approved_team(client, ah, "Robotics")
    pv = client.post(f"{API}/admin/allocation/preview", headers=ah, json={}).json()
    assigned = {a["team_id"]: a["faculty_name"] for a in pv["assignments"]}
    assert assigned == {t_cy["id"]: "CyberProf"}
    assert pv["unassigned"][0]["team_id"] == t_ml["id"] and "match" in pv["unassigned"][0]["reason"]
    a = pv["assignments"][0]
    for k in ("team_name", "project_title", "team_domain", "faculty_name", "score", "explanation",
              "faculty_current", "faculty_capacity", "remaining_after"):
        assert k in a


def test_parent_domain_and_supported_domain_match(client, ah):
    make_faculty(client, ah, "AiProf", ["Artificial Intelligence"], cap=2)       # ML is a child of AI
    make_faculty(client, ah, "WebSupport", ["Web Development"], supported=[CY], cap=2)
    t1 = approved_team(client, ah, ML)
    t2 = approved_team(client, ah, CY)
    pv = client.post(f"{API}/admin/allocation/preview", headers=ah, json={}).json()
    assigned = {a["team_id"]: a["faculty_name"] for a in pv["assignments"]}
    assert assigned == {t1["id"]: "AiProf", t2["id"]: "WebSupport"}


def test_stronger_match_preferred_over_workload(client, ah):
    make_faculty(client, ah, "Exact", [CY], cap=2)
    make_faculty(client, ah, "Weak", ["Web Development"], interests=[CY], cap=20)     # interest-only: 15 < min 20 -> incompatible
    approved_team(client, ah, CY)
    approved_team(client, ah, CY)
    pv, r = preview_and_commit(client, ah)
    assert counts(client, ah)["Exact"] == (2, 2) and counts(client, ah)["Weak"][0] == 0


def test_relative_workload_fairness_across_different_capacities(client, ah):
    make_faculty(client, ah, "Small", [CY], cap=2)
    make_faculty(client, ah, "Big", [CY], cap=10)
    for _ in range(4):
        approved_team(client, ah, CY)
    preview_and_commit(client, ah)
    c = counts(client, ah)
    assert c["Small"][0] <= 2 and c["Big"][0] <= 10
    assert c["Big"][0] > c["Small"][0]                    # larger capacity absorbs more...
    assert c["Small"][0] >= 1                              # ...but the small one still shares proportionally
    assert c["Small"][0] + c["Big"][0] == 4


def test_engine_is_deterministic():
    facs = lambda: [FacView(i, f"F{i}", "CSE", 3, 0, None, expertise={1}) for i in (3, 1, 2)]
    teams = [TeamView(i, f"T{i}", "t", "CSE", 1, set()) for i in (5, 4, 6)]
    strip = lambda o: (o["assignments"], o["unassigned"], o["faculty_projection"])
    r1 = strip(run_optimizer(teams, facs(), {}, {}, False))
    r2 = strip(run_optimizer(list(reversed(teams)), list(reversed(facs())), {}, {}, False))
    assert r1 == r2


def test_score_components():
    # fairness is no longer part of the pair score (the optimiser balances workload globally)
    t = TeamView(1, "T", "t", "CSE", 10, {11})
    f = FacView(1, "F", "CSE", 4, 1, None, expertise={10}, supported={11})
    s = score_pair(t, f, {}, False)
    assert s["domain_score"] == 50 + 7 and s["total"] == 50 + 7 + 10 and s["compatible"] and s["tier"] == 1


# ---------------- preview / commit / rerun ----------------
def test_preview_writes_nothing_and_commit_needs_confirmation(client, ah, db):
    make_faculty(client, ah, "AA", [CY], cap=3)
    approved_team(client, ah, CY)
    pv = client.post(f"{API}/admin/allocation/preview", headers=ah, json={}).json()
    assert db.scalar(select(func.count()).select_from(Allocation)) == 0
    assert client.post(f"{API}/admin/allocation/preview/{pv['id']}/commit", headers=ah, json={"confirm": False}).status_code == 422
    assert db.scalar(select(func.count()).select_from(Allocation)) == 0
    r = client.post(f"{API}/admin/allocation/preview/{pv['id']}/commit", headers=ah, json={"confirm": True})
    assert r.status_code == 200
    # retry is safe: no duplicate assignments
    again = client.post(f"{API}/admin/allocation/preview/{pv['id']}/commit", headers=ah, json={"confirm": True})
    assert again.status_code == 409
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Allocation)) == 1


def test_rerun_preserves_existing_and_only_handles_new_teams(client, ah, db):
    make_faculty(client, ah, "AA", [CY], cap=5)
    t1 = approved_team(client, ah, CY)
    preview_and_commit(client, ah)
    first = {a.team_id: (a.faculty_id, a.id) for a in db.scalars(select(Allocation))}
    t2 = approved_team(client, ah, CY)
    pv, r = preview_and_commit(client, ah)
    assert [a["team_id"] for a in pv["assignments"]] == [t2["id"]]
    db.expire_all()
    now = {a.team_id: (a.faculty_id, a.id) for a in db.scalars(select(Allocation))}
    assert now[t1["id"]] == first[t1["id"]] and len(now) == 2
    empty = client.post(f"{API}/admin/allocation/preview", headers=ah, json={}).json()
    assert empty["assignments"] == []


def test_commit_revalidates_capacity_and_eligibility(client, ah):
    f = make_faculty(client, ah, "AA", [CY], cap=2)
    approved_team(client, ah, CY)
    approved_team(client, ah, CY)
    pv = client.post(f"{API}/admin/allocation/preview", headers=ah, json={}).json()
    assert len(pv["assignments"]) == 2
    # between preview and commit capacity is cut to 1 and the faculty member is made unavailable for nobody else
    client.put(f"{API}/admin/faculty/{f['id']}/capacity", headers=ah, json={"max_capacity": 1, "reason": "leave"})
    r = client.post(f"{API}/admin/allocation/preview/{pv['id']}/commit", headers=ah, json={"confirm": True}).json()
    assert len(r["assigned"]) == 1 and len(r["skipped"]) == 1
    assert counts(client, ah)["AA"] == (1, 1)


def test_cannot_preview_without_active_cycle_or_after_finalise(client, ah):
    make_faculty(client, ah, "AA", [CY], cap=2)
    approved_team(client, ah, CY)
    preview_and_commit(client, ah)
    assert client.post(f"{API}/admin/allocation/finalise", headers=ah, json={"confirm": True}).status_code == 200
    assert client.post(f"{API}/admin/allocation/preview", headers=ah, json={}).status_code == 409


# ---------------- manual / reassignment / history ----------------
def test_manual_assignment_reassignment_and_history(client, ah, db):
    a = make_faculty(client, ah, "AA", [CY], cap=1)
    b = make_faculty(client, ah, "BB", [CY], cap=1)
    c = make_faculty(client, ah, "CC", [IOT], cap=3)
    t = approved_team(client, ah, CY)
    pre = client.get(f"{API}/admin/allocation/manual-preview", headers=ah, params={"team_id": t["id"], "faculty_id": a["id"]}).json()
    assert pre["can_assign"] and pre["faculty_remaining_after"] == 0
    assert client.post(f"{API}/admin/allocation/manual", headers=ah,
                       json={"team_id": t["id"], "faculty_id": a["id"]}).status_code == 422     # needs confirm
    assert client.post(f"{API}/admin/allocation/manual", headers=ah,
                       json={"team_id": t["id"], "faculty_id": a["id"], "confirm": True}).status_code == 200
    # incompatible faculty rejected (same rules as automatic allocation)
    assert client.post(f"{API}/admin/allocation/manual", headers=ah,
                       json={"team_id": t["id"], "faculty_id": c["id"], "reason": "x y z", "confirm": True}).status_code == 409
    # reassignment requires a reason
    assert client.post(f"{API}/admin/allocation/manual", headers=ah,
                       json={"team_id": t["id"], "faculty_id": b["id"], "confirm": True}).status_code == 422
    assert client.post(f"{API}/admin/allocation/manual", headers=ah,
                       json={"team_id": t["id"], "faculty_id": b["id"], "reason": "Workload balancing", "confirm": True}).status_code == 200
    cnt = counts(client, ah)
    assert cnt["AA"][0] == 0 and cnt["BB"][0] == 1
    hist = client.get(f"{API}/admin/allocation-history", headers=ah, params={"team_id": t["id"]}).json()["items"]
    assert [h["action"] for h in hist] == ["reassign", "manual_assign"]
    assert hist[0]["old_faculty"] == "AA" and hist[0]["new_faculty"] == "BB" and hist[0]["reason"] == "Workload balancing"
    # one team can never hold two allocations
    assert db.scalar(select(func.count()).select_from(Allocation)) == 1
    # full faculty cannot take another team
    t2 = approved_team(client, ah, CY)
    assert client.post(f"{API}/admin/allocation/manual", headers=ah,
                       json={"team_id": t2["id"], "faculty_id": b["id"], "confirm": True}).status_code == 409
    cand = client.get(f"{API}/admin/allocation/candidates/{t2['id']}", headers=ah).json()["faculty"]
    assert next(x for x in cand if x["name"] == "BB")["eligible"] is False
    # unassign requires reason, returns team to the pool
    assert client.post(f"{API}/admin/allocation/unassign", headers=ah, json={"team_id": t["id"], "reason": "re-plan", "confirm": True}).status_code == 200
    assert counts(client, ah)["BB"][0] == 0
    assert client.get(f"{API}/team/guide", headers=t["headers"]).json()["allocation"] is None


# ---------------- capacity reduction ----------------
def test_capacity_reduction_below_assigned(client, ah, db):
    f = make_faculty(client, ah, "AA", [CY], cap=3)
    for _ in range(3):
        approved_team(client, ah, CY)
    preview_and_commit(client, ah)
    assert counts(client, ah)["AA"] == (3, 3)
    r = client.put(f"{API}/admin/faculty/{f['id']}/capacity", headers=ah, json={"max_capacity": 1, "reason": "Sabbatical"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "capacity_below_assigned"
    assert r.json()["detail"]["assigned"] == 3
    assert counts(client, ah)["AA"] == (3, 3)                                    # nothing changed
    r = client.put(f"{API}/admin/faculty/{f['id']}/capacity", headers=ah,
                   json={"max_capacity": 1, "reason": "Sabbatical", "confirm_below_assigned": True})
    assert r.status_code == 200 and r.json()["over_capacity"] is True
    assert counts(client, ah)["AA"] == (3, 1)                                    # assignments untouched
    approved_team(client, ah, CY)
    pv = client.post(f"{API}/admin/allocation/preview", headers=ah, json={}).json()
    # AA is the only compatible mentor: the team is still allocated, flagged as overload (needs acknowledgement)
    assert len(pv["assignments"]) == 1 and pv["assignments"][0]["overload"] == 3 and pv["summary"]["new_overload"] == 1
    ch = db.scalars(select(CapacityChange).where(CapacityChange.reason == "Sabbatical")).all()   # (approval logs its own row)
    assert len(ch) == 1 and (ch[0].old_capacity, ch[0].new_capacity, ch[0].reason) == (3, 1, "Sabbatical")
    assert ch[0].changed_by is not None and ch[0].created_at is not None
    detail = client.get(f"{API}/admin/faculty/{f['id']}", headers=ah).json()
    assert detail["capacity_history"][0]["new"] == 1
    # finalisation is blocked until compliance is restored
    r = client.post(f"{API}/admin/allocation/finalise", headers=ah, json={"confirm": True})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "finalise_blocked"


def test_capacity_edit_requires_reason_and_admin(client, ah):
    f = make_faculty(client, ah, "AA", [CY], cap=3)
    assert client.put(f"{API}/admin/faculty/{f['id']}/capacity", headers=ah, json={"max_capacity": 4}).status_code == 422
    assert client.put(f"{API}/admin/faculty/{f['id']}/capacity", headers=ah, json={"max_capacity": 4, "reason": "ok ok"}).status_code == 200
    assert client.get(f"{API}/faculty/me", headers=f["headers"]).json()["workload"]["max_capacity"] == 4


# ---------------- finalisation ----------------
def test_finalise_preserves_allocations_and_requires_reason_to_change(client, ah, db):
    a = make_faculty(client, ah, "AA", [CY], cap=2)
    b = make_faculty(client, ah, "BB", [CY], cap=2)
    t = approved_team(client, ah, CY)
    preview_and_commit(client, ah)
    assert client.post(f"{API}/admin/allocation/finalise", headers=ah, json={"confirm": False}).status_code == 422
    assert client.post(f"{API}/admin/allocation/finalise", headers=ah, json={"confirm": True}).status_code == 200
    assert client.post(f"{API}/admin/allocation/finalise", headers=ah, json={"confirm": True}).status_code == 409
    al = db.scalar(select(Allocation))
    assert al.status == "finalised" and al.finalised_at is not None
    guide = client.get(f"{API}/team/guide", headers=t["headers"]).json()["allocation"]
    assert guide["status"] == "finalised"
    assert client.get(f"{API}/team/proposal", headers=t["headers"]).json()["status"] == "finalised"
    other = b["id"] if guide["faculty"]["id"] == a["id"] else a["id"]
    assert client.post(f"{API}/admin/allocation/manual", headers=ah, json={"team_id": t["id"], "faculty_id": other, "confirm": True}).status_code == 422
    r = client.post(f"{API}/admin/allocation/manual", headers=ah, json={"team_id": t["id"], "faculty_id": other,
                                                                         "reason": "Admin override", "confirm": True})
    assert r.status_code == 200 and r.json()["status"] == "finalised"
    assert client.get(f"{API}/admin/audit-logs", headers=ah, params={"action": "allocation.reassign"}).json()["total"] == 1
    # the faculty member sees the team with members and proposal
    mine = client.get(f"{API}/faculty/me/teams", headers=(a if other == a["id"] else b)["headers"]).json()
    assert len(mine) == 1 and len(mine[0]["team"]["members"]) == 2 and mine[0]["proposal"]["title"]


def test_new_cycle_does_not_touch_old_allocations(client, ah, db):
    make_faculty(client, ah, "AA", [CY], cap=1)
    approved_team(client, ah, CY)
    preview_and_commit(client, ah)
    client.post(f"{API}/admin/allocation/finalise", headers=ah, json={"confirm": True})
    old_cycle = client.get(f"{API}/admin/cycles", headers=ah).json()[0]["id"]
    new_id = new_cycle(client, ah, "2027-28")
    assert new_id != old_cycle
    w = workload(client, ah)
    assert w["cycle"]["id"] == new_id and counts(client, ah)["AA"] == (0, 1)       # capacity is interpreted per cycle
    old = client.get(f"{API}/admin/workload", headers=ah, params={"cycle_id": old_cycle}).json()
    assert {f["name"]: f["assigned"] for f in old["faculty"]}["AA"] == 1
    pv = client.post(f"{API}/admin/allocation/preview", headers=ah, json={}).json()
    assert pv["assignments"] == []                                                # finalised old assignment not re-run
    hist = client.get(f"{API}/admin/reports/allocations", headers=ah, params={"cycle_id": old_cycle}).json()
    assert len(hist["rows"]) == 1


# ---------------- concurrency and rollback ----------------
def test_concurrent_commits_of_same_preview_assign_once(client, ah, db):
    make_faculty(client, ah, "AA", [CY], cap=5)
    for _ in range(3):
        approved_team(client, ah, CY)
    pv = client.post(f"{API}/admin/allocation/preview", headers=ah, json={}).json()
    results = []

    def go():
        c = TestClient(app)
        results.append(c.post(f"{API}/admin/allocation/preview/{pv['id']}/commit", headers=ah, json={"confirm": True}).status_code)

    ts = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(results) == [200, 409, 409, 409]
    assert db.scalar(select(func.count()).select_from(Allocation)) == 3
    assert db.scalar(select(func.count()).select_from(AllocationHistory)) == 3


def test_concurrent_manual_assignments_never_exceed_capacity(client, ah, db):
    f = make_faculty(client, ah, "AA", [CY], cap=1)
    teams = [approved_team(client, ah, CY) for _ in range(4)]
    results = []

    def go(t):
        c = TestClient(app)
        results.append(c.post(f"{API}/admin/allocation/manual", headers=ah,
                              json={"team_id": t["id"], "faculty_id": f["id"], "confirm": True}).status_code)

    ts = [threading.Thread(target=go, args=(t,)) for t in teams]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(results) == [200, 409, 409, 409]
    assert db.scalar(select(func.count()).select_from(Allocation)) == 1


def test_failed_commit_rolls_back_everything(client, ah, db, monkeypatch):
    make_faculty(client, ah, "AA", [CY], cap=5)
    for _ in range(3):
        approved_team(client, ah, CY)
    pv = client.post(f"{API}/admin/allocation/preview", headers=ah, json={}).json()
    import app.services.allocation as svc
    calls = {"n": 0}
    real = svc._announce

    def boom(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated failure")
        return real(*a, **k)

    monkeypatch.setattr(svc, "_announce", boom)
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post(f"{API}/admin/allocation/preview/{pv['id']}/commit", headers=ah, json={"confirm": True})
    assert r.status_code == 500 and "simulated" not in r.text                     # no internals leaked
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Allocation)) == 0
    assert db.scalar(select(func.count()).select_from(AllocationHistory)) == 0
    assert db.get(AllocationPreview, pv["id"]).status == "pending"
    monkeypatch.setattr(svc, "_announce", real)                                   # retry succeeds afterwards
    assert client.post(f"{API}/admin/allocation/preview/{pv['id']}/commit", headers=ah, json={"confirm": True}).status_code == 200
    assert db.scalar(select(func.count()).select_from(Allocation)) == 3
