import pytest

from tests.helpers import (API, admin_headers, approved_team, domain_ids, make_faculty, new_cycle, preview_and_commit,
                           register_team)


@pytest.fixture
def ah(client):
    h = admin_headers(client)
    new_cycle(client, h)
    return h


def _proposal(ids, **kw):
    base = {"title": "Smart Campus Monitor", "description": "A long enough description of the intended project work.",
            "primary_domain_id": ids["Internet of Things"], "interest_domain_ids": [], "technologies": ["MQTT", "Python"]}
    base.update(kw)
    return base


def test_leader_sees_own_team_only(client, ah):
    p1, h1 = register_team(client, name="Alpha")
    p2, h2 = register_team(client, name="Beta")
    t1 = client.get(f"{API}/team", headers=h1).json()
    assert t1["name"] == "Alpha" and len(t1["members"]) == 3 and t1["leader"]["email"] == p1["leader"]["email"]
    assert client.get(f"{API}/team", headers=h2).json()["name"] == "Beta"
    other_member = client.get(f"{API}/team", headers=h2).json()["members"][1]["id"]
    # cannot touch another team's member, and admin routes are closed to leaders
    assert client.put(f"{API}/team/members/{other_member}", headers=h1, json={"full_name": "Hacked"}).status_code == 404
    assert client.delete(f"{API}/team/members/{other_member}", headers=h1).status_code == 404
    assert client.get(f"{API}/admin/teams/{t1['id']}", headers=h1).status_code == 403
    assert client.get(f"{API}/team").status_code == 401


def test_proposal_submit_review_and_edit_restrictions(client, ah):
    ids = domain_ids(client)
    _, lh = register_team(client)
    assert client.post(f"{API}/team/proposal/submit", headers=lh).status_code == 422       # nothing filled in yet
    assert client.put(f"{API}/team/proposal", headers=lh, json=_proposal(ids)).status_code == 200
    r = client.post(f"{API}/team/proposal/submit", headers=lh)
    assert r.status_code == 200 and r.json()["status"] == "submitted"
    # locked after submission
    assert client.put(f"{API}/team/proposal", headers=lh, json=_proposal(ids, title="Changed title")).status_code == 409
    assert client.post(f"{API}/team/members", headers=lh, json={"full_name": "New Kid", "email": "n@srmist.edu.in",
                                                                  "registration_number": "RA2611003040903"}).status_code == 409
    pid = r.json()["id"]
    # revision requires remarks
    assert client.post(f"{API}/admin/proposals/{pid}/review", headers=ah, json={"action": "request_revision"}).status_code == 422
    assert client.post(f"{API}/admin/proposals/{pid}/review", headers=ah,
                       json={"action": "request_revision", "remarks": "Add objectives"}).status_code == 200
    prop = client.get(f"{API}/team/proposal", headers=lh).json()
    assert prop["status"] == "needs_revision" and prop["admin_remarks"] == "Add objectives"
    assert client.put(f"{API}/team/proposal", headers=lh, json=_proposal(ids, objectives="Objectives added")).status_code == 200
    assert client.post(f"{API}/team/proposal/submit", headers=lh).status_code == 200
    assert client.post(f"{API}/admin/proposals/{pid}/review", headers=ah, json={"action": "approve"}).status_code == 200
    assert client.get(f"{API}/team/proposal", headers=lh).json()["eligible_for_allocation"] is True
    assert len(client.get(f"{API}/team/proposal", headers=lh).json()["reviews"]) >= 4
    notes = client.get(f"{API}/notifications", headers=lh).json()["items"]
    assert any("approved" in n["message"] for n in notes)
    assert client.get(f"{API}/notifications/unread-count", headers=lh).json()["unread"] >= 3


def test_rejected_proposal_not_eligible_and_not_allocated(client, ah):
    ids = domain_ids(client)
    _, lh = register_team(client)
    client.put(f"{API}/team/proposal", headers=lh, json=_proposal(ids))
    pid = client.post(f"{API}/team/proposal/submit", headers=lh).json()["id"]
    assert client.post(f"{API}/admin/proposals/{pid}/review", headers=ah, json={"action": "reject"}).status_code == 422
    assert client.post(f"{API}/admin/proposals/{pid}/review", headers=ah,
                       json={"action": "reject", "remarks": "Out of scope"}).status_code == 200
    make_faculty(client, ah, "Dr IoT", ["Internet of Things"], cap=3)
    pv = client.post(f"{API}/admin/allocation/preview", headers=ah, json={}).json()
    assert pv["assignments"] == [] and pv["unassigned"] == []          # rejected team is not in the pool
    reasons = client.get(f"{API}/admin/allocation/unallocated", headers=ah).json()
    assert reasons[0]["reason"] == "Proposal was rejected."


def test_other_domain_requires_custom_text_and_is_saved(client, ah):
    ids = domain_ids(client)
    _, lh = register_team(client)
    r = client.put(f"{API}/team/proposal", headers=lh, json=_proposal(ids, primary_domain_id=ids["Other"]))
    assert r.status_code == 422 and "custom domain" in r.json()["detail"].lower()
    r = client.put(f"{API}/team/proposal", headers=lh,
                   json=_proposal(ids, primary_domain_id=ids["Other"], custom_domain_name="Space Debris Tracking"))
    assert r.status_code == 200
    assert r.json()["primary_domain"]["name"] == "Space Debris Tracking" and r.json()["primary_domain"]["custom_status"] == "pending"
    doms = client.get(f"{API}/admin/domains", headers=ah, params={"custom_status": "pending"}).json()["items"]
    assert [d["name"] for d in doms] == ["Space Debris Tracking"] and doms[0]["team_usage"] == 1
    assert "Space Debris Tracking" not in domain_ids(client)           # not offered publicly until reviewed
    # a custom name without choosing Other is rejected
    r = client.put(f"{API}/team/proposal", headers=lh, json=_proposal(ids, custom_domain_name="Sneaky"))
    assert r.status_code == 422


def test_invalid_and_duplicate_domain_ids(client, ah):
    ids = domain_ids(client)
    _, lh = register_team(client)
    assert client.put(f"{API}/team/proposal", headers=lh, json=_proposal(ids, primary_domain_id=99999)).status_code == 422
    r = client.put(f"{API}/team/proposal", headers=lh, json=_proposal(
        ids, interest_domain_ids=[ids["Cybersecurity"], ids["Cybersecurity"], ids["Internet of Things"]]))
    assert r.status_code == 200
    assert [d["name"] for d in r.json()["interest_domains"]] == ["Cybersecurity"]    # dupes + primary repeat removed


def test_deactivated_domain_keeps_references(client, ah):
    ids = domain_ids(client)
    _, lh = register_team(client)
    client.put(f"{API}/team/proposal", headers=lh, json=_proposal(ids))
    r = client.patch(f"{API}/admin/domains/{ids['Internet of Things']}", headers=ah, json={"is_active": False})
    assert r.status_code == 200
    assert client.get(f"{API}/team/proposal", headers=lh).json()["primary_domain"]["name"] == "Internet of Things"
    assert "Internet of Things" not in domain_ids(client)
    assert client.patch(f"{API}/admin/domains/{ids['Other']}", headers=ah, json={"is_active": False}).status_code == 409


def test_leader_can_edit_team_members_before_submission_with_validation(client, ah):
    _, lh = register_team(client, size=2)
    t = client.get(f"{API}/team", headers=lh).json()
    r = client.post(f"{API}/team/members", headers=lh, json={"full_name": "Added One", "email": "added1@srmist.edu.in",
                                                              "registration_number": "RA2611003040904"})
    assert r.status_code == 201
    assert client.get(f"{API}/team", headers=lh).json()["members"][-1]["department"] == "CSE"   # defaults to team's
    assert client.post(f"{API}/team/members", headers=lh, json={"full_name": "Added Two", "email": "added1@srmist.edu.in",
                                                                  "registration_number": "RA2611003040905"}).status_code == 409
    leader_id = next(m["id"] for m in t["members"] if m["is_leader"])
    assert client.delete(f"{API}/team/members/{leader_id}", headers=lh).status_code == 422
    added = client.get(f"{API}/team", headers=lh).json()["members"][-1]["id"]
    assert client.delete(f"{API}/team/members/{added}", headers=lh).status_code == 204
    other = next(m["id"] for m in t["members"] if not m["is_leader"])
    assert client.delete(f"{API}/team/members/{other}", headers=lh).status_code == 422          # would drop below minimum


def test_finalised_membership_changes_need_admin(client, ah):
    f = make_faculty(client, ah, "Dr IoT", ["Internet of Things"], cap=2)
    t = approved_team(client, ah, "Internet of Things")
    _, r = preview_and_commit(client, ah)
    assert r.status_code == 200
    assert client.post(f"{API}/admin/allocation/finalise", headers=ah, json={"confirm": True}).status_code == 200
    body = {"full_name": "Late Joiner", "email": "late@srmist.edu.in", "registration_number": "RA2611003040906"}
    assert client.post(f"{API}/team/members", headers=t["headers"], json=body).status_code == 403
    assert client.put(f"{API}/team", headers=t["headers"], json={"name": "Renamed"}).status_code == 403
    team = client.get(f"{API}/team", headers=t["headers"]).json()
    assert team["editable"] is False and team["edit_block_code"] == "finalised"
    cr = client.post(f"{API}/team/change-requests", headers=t["headers"], json={"description": "Please add Late Joiner to our team."})
    assert cr.status_code == 201
    pending = client.get(f"{API}/admin/change-requests", headers=ah).json()["items"]
    assert len(pending) == 1
    assert client.post(f"{API}/admin/change-requests/{pending[0]['id']}/resolve", headers=ah,
                       json={"action": "approve", "remarks": "OK"}).status_code == 200
    # admin applies the correction (audited)
    r = client.post(f"{API}/admin/teams/{team['id']}/members", headers=ah, json=body)
    assert r.status_code == 201
    logs = client.get(f"{API}/admin/audit-logs", headers=ah, params={"action": "admin.team_member_add"}).json()["items"]
    assert len(logs) == 1


def test_admin_can_correct_team_with_audit_trail(client, ah):
    p, lh = register_team(client)
    t = client.get(f"{API}/team", headers=lh).json()
    mid = t["members"][1]["id"]
    r = client.put(f"{API}/admin/teams/{t['id']}/members/{mid}", headers=ah, json={"registration_number": "RA2611003040907"})
    assert r.status_code == 200 and r.json()["registration_number"] == "RA2611003040907"
    assert client.get(f"{API}/admin/audit-logs", headers=ah, params={"action": "admin.team_member_update"}).json()["total"] == 1


def test_admin_team_list_search_filter_sort_pagination(client, ah):
    for n in ("Zeta", "Alpha", "Mid"):
        register_team(client, name=n)
    r = client.get(f"{API}/admin/teams", headers=ah, params={"sort": "name", "page_size": 2}).json()
    assert r["total"] == 3 and [x["name"] for x in r["items"]] == ["Alpha", "Mid"]
    r = client.get(f"{API}/admin/teams", headers=ah, params={"search": "zeta"}).json()
    assert [x["name"] for x in r["items"]] == ["Zeta"]
    r = client.get(f"{API}/admin/teams", headers=ah, params={"sort": "-name", "page": 2, "page_size": 2}).json()
    assert [x["name"] for x in r["items"]] == ["Alpha"]
