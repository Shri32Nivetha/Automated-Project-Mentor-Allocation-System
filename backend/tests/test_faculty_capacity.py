"""Faculty approval: capacity validation, persistence, engine integration, warnings and authorization."""
import pytest
from sqlalchemy import select

from app.models import CapacityChange, FacultyCycleCapacity, FacultyProfile
from tests.helpers import API, admin_headers, approved_team, make_faculty, new_cycle, preview_and_commit

CY = "Cybersecurity"


@pytest.fixture
def ah(client):
    h = admin_headers(client)
    new_cycle(client, h)
    return h


def pending(client, ah, name="Pend Ing"):
    f = make_faculty(client, ah, name, [CY], cap=4, approve=False)
    return f


def approve(client, ah, f, **body):
    return client.post(f"{API}/admin/faculty/{f['id']}/approve", headers=ah, json=body)


@pytest.mark.parametrize("bad,fragment", [
    (None, "Enter"), (0, "at least 1"), (-3, "at least 1"), (101, "more than 100"), (2.5, "whole number"),
    ("5", "whole number"), ("abc", "whole number"), (True, "whole number"), ("", "Enter")])
def test_invalid_capacity_is_rejected_with_field_error(client, ah, db, bad, fragment):
    f = pending(client, ah)
    r = approve(client, ah, f) if bad is None else approve(client, ah, f, capacity=bad)
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert d["errors"][0]["field"] == "capacity" and fragment in d["errors"][0]["message"]
    assert db.get(FacultyProfile, f["id"]).approval_status == "pending"          # nothing was approved


def test_valid_capacity_is_persisted_and_used_by_the_engine(client, ah, db):
    f = pending(client, ah)
    r = approve(client, ah, f, capacity=7, remarks="welcome")
    assert r.status_code == 200 and r.json()["capacity"] == 7
    db.expire_all()
    assert db.get(FacultyProfile, f["id"]).max_capacity == 7
    row = db.scalar(select(FacultyCycleCapacity).where(FacultyCycleCapacity.faculty_id == f["id"]))
    assert row.max_capacity == 7
    assert db.scalar(select(CapacityChange).where(CapacityChange.faculty_id == f["id"])).new_capacity == 7
    detail = client.get(f"{API}/admin/faculty/{f['id']}", headers=ah).json()
    assert detail["workload"]["max_capacity"] == 7 and detail["capacity_limits"] == {"min": 1, "max": 100}
    for _ in range(8):
        approved_team(client, ah, CY)
    pv = client.post(f"{API}/admin/allocation/preview", headers=ah, json={}).json()
    row = next(p for p in pv["faculty_projection"] if p["faculty_id"] == f["id"])
    assert row["capacity"] == 7 and row["projected"] == 8 and row["overload"] == 1   # the saved value drove the plan


def test_limits_are_configurable(client, ah):
    client.put(f"{API}/admin/settings", headers=ah, json={"values": {"max_faculty_capacity": 12}})
    f = pending(client, ah)
    assert approve(client, ah, f, capacity=13).status_code == 422
    assert approve(client, ah, f, capacity=12).status_code == 200
    assert client.put(f"{API}/admin/settings", headers=ah, json={"values": {"min_faculty_capacity": 20}}).status_code == 422


def test_duplicate_approval_is_rejected(client, ah):
    f = pending(client, ah)
    assert approve(client, ah, f, capacity=3).status_code == 200
    assert approve(client, ah, f, capacity=9).status_code == 409


def test_capacity_edit_validates_and_warns_about_overload_without_removing_teams(client, ah):
    f = make_faculty(client, ah, "Busy Prof", [CY], cap=3)
    for _ in range(3):
        approved_team(client, ah, CY)
    preview_and_commit(client, ah)
    for bad in (2.5, "x", -1, 0, 500):
        assert client.put(f"{API}/admin/faculty/{f['id']}/capacity", headers=ah,
                          json={"max_capacity": bad, "reason": "test"}).status_code == 422
    r = client.put(f"{API}/admin/faculty/{f['id']}/capacity", headers=ah, json={"max_capacity": 1, "reason": "leave"})
    d = r.json()["detail"]
    assert r.status_code == 409 and d["code"] == "capacity_below_assigned" and d["assigned"] == 3 and d["overload"] == 2
    ok = client.put(f"{API}/admin/faculty/{f['id']}/capacity", headers=ah,
                    json={"max_capacity": 1, "reason": "leave", "confirm_below_assigned": True}).json()
    assert ok["overload"] == 2
    listed = client.get(f"{API}/admin/faculty", headers=ah, params={"workload": "over"}).json()["items"]
    assert [x["id"] for x in listed] == [f["id"]] and listed[0]["assigned"] == 3          # teams were not removed


def test_stale_capacity_edit_is_refused(client, ah):
    f = make_faculty(client, ah, "Race Prof", [CY], cap=3)
    client.put(f"{API}/admin/faculty/{f['id']}/capacity", headers=ah, json={"max_capacity": 5, "reason": "first"})
    r = client.put(f"{API}/admin/faculty/{f['id']}/capacity", headers=ah,
                   json={"max_capacity": 6, "reason": "second", "expected_capacity": 3})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "capacity_changed"


def test_unauthorized_users_cannot_approve_or_change_capacity(client, ah):
    f = pending(client, ah)
    other = make_faculty(client, ah, "Other Prof", [CY], cap=2)
    t = approved_team(client, ah, CY)
    assert approve(client, other["headers"], f, capacity=5).status_code == 403
    assert approve(client, t["headers"], f, capacity=5).status_code == 403
    assert client.post(f"{API}/admin/faculty/{f['id']}/approve", json={"capacity": 5}).status_code == 401
    assert client.put(f"{API}/admin/faculty/{other['id']}/capacity", headers=other["headers"],
                      json={"max_capacity": 99, "reason": "self service"}).status_code == 403


def test_faculty_list_filters_and_sorting(client, ah):
    a = make_faculty(client, ah, "Aa Prof", [CY], cap=2, dept="CSE")
    make_faculty(client, ah, "Bb Prof", [CY], cap=9, dept="ECE", available=False)
    r = client.get(f"{API}/admin/faculty", headers=ah, params={"department": "ECE"}).json()
    assert [x["full_name"] for x in r["items"]] == ["Bb Prof"]
    r = client.get(f"{API}/admin/faculty", headers=ah, params={"available": "true"}).json()
    assert [x["id"] for x in r["items"]] == [a["id"]]
    r = client.get(f"{API}/admin/faculty", headers=ah, params={"sort": "-capacity"}).json()
    assert [x["max_capacity"] for x in r["items"]] == [9, 2]
    meta = client.get(f"{API}/admin/faculty-meta", headers=ah).json()
    assert meta["departments"] == ["CSE", "ECE"] and meta["capacity_limits"]["max"] == 100


def test_dashboard_reports_real_resolution_overload_and_activity(client, ah):
    make_faculty(client, ah, "Solo Prof", [CY], cap=1)
    make_faculty(client, ah, "Pending Prof", [CY], cap=1, approve=False)
    for _ in range(2):
        approved_team(client, ah, CY)
    approved_team(client, ah, "Robotics")
    preview_and_commit(client, ah)
    d = client.get(f"{API}/admin/dashboard", headers=ah).json()
    assert d["allocated_teams"] == 2 and d["approved_faculty"] == 1 and d["pending_faculty_approvals"] == 1
    assert d["overloaded_faculty"] == 1 and d["total_overload"] == 1 and d["teams_requiring_resolution"] == 1
    assert d["recent_allocation_activity"][0]["action"] == "auto_assign"
