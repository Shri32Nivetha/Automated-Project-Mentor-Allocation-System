import pytest
from sqlalchemy import func, select

from app.models import Team, TeamMember, User
from app.security import verify_password
from tests.helpers import API, PW, admin_headers, hdr, login, make_faculty, member, new_cycle, register_team, team_payload


@pytest.fixture
def ah(client):
    h = admin_headers(client)
    new_cycle(client, h)
    return h


def test_team_registration_stores_leader_and_all_members(client, db, ah):
    p, lh = register_team(client, size=4)
    users = db.scalars(select(User).where(User.role == "team_leader")).all()
    assert len(users) == 1                                # only the leader gets a login
    assert db.scalar(select(func.count()).select_from(User)) == 2   # admin + leader
    team = db.scalar(select(Team))
    assert team.leader_user_id == users[0].id
    assert len(team.members) == 4 and sum(m.is_leader for m in team.members) == 1
    assert {m.registration_number for m in team.members} == {p["leader"]["registration_number"]} | {
        m["registration_number"] for m in p["members"]}
    assert team.proposal.status == "draft"


def test_password_is_hashed(client, db, ah):
    p, _ = register_team(client)
    u = db.scalar(select(User).where(User.email == p["leader"]["email"]))
    assert u.password_hash != PW and u.password_hash.startswith("$2")
    assert verify_password(PW, u.password_hash) and not verify_password("wrong", u.password_hash)


def test_team_size_limits_and_configurable_settings(client, ah):
    r = client.post(f"{API}/register/team", json=team_payload(size=1))
    assert r.status_code == 422                            # default minimum is 2
    r = client.post(f"{API}/register/team", json=team_payload(size=5))
    assert r.status_code == 422                            # default maximum is 4
    r = client.put(f"{API}/admin/settings", headers=ah, json={"values": {"max_team_size": 5}})
    assert r.status_code == 200
    r = client.post(f"{API}/register/team", json=team_payload(size=5))
    assert r.status_code == 201
    bad = client.put(f"{API}/admin/settings", headers=ah, json={"values": {"min_team_size": 6, "max_team_size": 5}})
    assert bad.status_code == 422


def test_number_of_members_must_match(client, ah):
    p = team_payload(size=3)
    p["number_of_members"] = 4
    assert client.post(f"{API}/register/team", json=p).status_code == 422


def test_duplicate_registration_number_and_email(client, ah):
    p1, _ = register_team(client)
    p2 = team_payload()
    p2["members"][0]["registration_number"] = p1["members"][0]["registration_number"]
    r = client.post(f"{API}/register/team", json=p2)
    assert r.status_code == 409 and "Registration number" in r.json()["detail"]
    p3 = team_payload()
    p3["members"][0]["email"] = p1["members"][0]["email"].upper()      # normalisation
    r = client.post(f"{API}/register/team", json=p3)
    assert r.status_code == 409 and "E-mail" in r.json()["detail"]


def test_same_student_cannot_join_two_teams_even_with_different_formatting(client, ah):
    p1, _ = register_team(client)
    p2 = team_payload()
    p2["members"][0] = {**p2["members"][0], "registration_number": " " + p1["members"][0]["registration_number"].lower() + " ",
                        "email": "different@srmist.edu.in"}
    assert client.post(f"{API}/register/team", json=p2).status_code == 409


def test_duplicates_inside_one_request_rejected(client, ah):
    p = team_payload(size=3)
    p["members"][1]["registration_number"] = p["members"][0]["registration_number"]
    assert client.post(f"{API}/register/team", json=p).status_code == 422


def test_cross_department_rule_is_configurable(client, ah):
    p = team_payload()
    p["members"][0]["department"] = "ECE"
    assert client.post(f"{API}/register/team", json=p).status_code == 422
    client.put(f"{API}/admin/settings", headers=ah, json={"values": {"allow_cross_department": True}})
    assert client.post(f"{API}/register/team", json=p).status_code == 201


def test_registration_requires_active_cycle(client):
    r = client.post(f"{API}/register/team", json=team_payload())
    assert r.status_code == 409


def test_login_success_and_failures(client, ah):
    p, lh = register_team(client)
    me = client.get(f"{API}/auth/me", headers=lh).json()
    assert me["role"] == "team_leader" and me["email"] == p["leader"]["email"]
    bad = client.post(f"{API}/auth/login", json={"email": p["leader"]["email"], "password": "nope12345"})
    assert bad.status_code == 401
    ghost = client.post(f"{API}/auth/login", json={"email": "ghost@srmist.edu.in", "password": "nope12345"})
    assert ghost.status_code == 401 and ghost.json() == bad.json()      # no user enumeration


def test_login_rate_limit(client, ah):
    p, _ = register_team(client)
    codes = [client.post(f"{API}/auth/login", json={"email": p["leader"]["email"], "password": "bad-pass1"}).status_code
             for _ in range(12)]
    assert codes[0] == 401 and codes[-1] == 429


def test_no_token_or_forged_token(client, ah):
    assert client.get(f"{API}/auth/me").status_code == 401
    assert client.get(f"{API}/auth/me", headers=hdr("not.a.token")).status_code == 401
    from jose import jwt
    forged = jwt.encode({"sub": "1", "tv": 0, "role": "admin"}, "wrong-secret-wrong-secret-wrong-secret", algorithm="HS256")
    assert client.get(f"{API}/admin/dashboard", headers=hdr(forged)).status_code == 401


def test_role_in_payload_cannot_escalate(client, ah):
    p = team_payload()
    p["role"] = "admin"
    assert client.post(f"{API}/register/team", json=p).status_code == 422       # extra fields forbidden
    assert client.post(f"{API}/register/admin", json={"email": "x@y.edu"}).status_code in (404, 405)
    _, lh = register_team(client)
    assert client.get(f"{API}/admin/dashboard", headers=lh).status_code == 403


def test_faculty_registration_pending_then_approve_reject(client, ah):
    f = make_faculty(client, ah, "Dr Pending", ["Cybersecurity"], approve=False)
    prof = client.get(f"{API}/faculty/me", headers=f["headers"]).json()
    assert prof["approval_status"] == "pending"
    assert prof["workload"]["can_receive_new"] is False
    assert client.post(f"{API}/admin/faculty/{f['id']}/approve", headers=ah, json={"capacity": 4}).status_code == 200
    assert client.get(f"{API}/faculty/me", headers=f["headers"]).json()["approval_status"] == "approved"
    g = make_faculty(client, ah, "Dr Reject", ["Cybersecurity"], approve=False)
    assert client.post(f"{API}/admin/faculty/{g['id']}/reject", headers=ah, json={"remarks": "Incomplete"}).status_code == 200
    assert client.get(f"{API}/faculty/me", headers=g["headers"]).json()["approval_status"] == "rejected"


def test_faculty_cannot_self_approve_or_change_capacity(client, ah):
    f = make_faculty(client, ah, "Dr Self", ["Cybersecurity"], approve=False, cap=2)
    assert client.post(f"{API}/admin/faculty/{f['id']}/approve", headers=f["headers"], json={}).status_code == 403
    r = client.put(f"{API}/faculty/me", headers=f["headers"], json={"max_capacity": 99})
    assert r.status_code == 422
    r = client.put(f"{API}/faculty/me", headers=f["headers"], json={"approval_status": "approved"})
    assert r.status_code == 422
    r = client.put(f"{API}/admin/faculty/{f['id']}/capacity", headers=f["headers"], json={"max_capacity": 50, "reason": "me"})
    assert r.status_code == 403
    other = make_faculty(client, ah, "Dr Other", ["Cybersecurity"])
    assert client.patch(f"{API}/admin/faculty/{other['id']}", headers=f["headers"], json={"designation": "HOD"}).status_code == 403


def test_faculty_registration_duplicates_and_invalid_domain(client, ah):
    f = make_faculty(client, ah, "Dr A", ["Cybersecurity"])
    r = client.post(f"{API}/register/faculty", json={
        "full_name": "Dr B", "email": "other@srmist.edu.in", "employee_id": "emp0001", "department": "CSE",
        "designation": "Professor", "password": PW, "expertise_domain_ids": [9999], "requested_capacity": 3})
    assert r.status_code in (409, 422)
    r = client.post(f"{API}/register/faculty", json={
        "full_name": "Dr B", "email": "other@srmist.edu.in", "employee_id": "NEWEMP", "department": "CSE",
        "designation": "Professor", "password": PW, "expertise_domain_ids": [9999], "requested_capacity": 3})
    assert r.status_code == 422


def test_change_password_invalidates_old_tokens(client, ah):
    p, lh = register_team(client)
    r = client.post(f"{API}/auth/change-password", headers=lh, json={"current_password": PW, "new_password": "NewPass123"})
    assert r.status_code == 200
    assert client.get(f"{API}/auth/me", headers=lh).status_code == 401
    login(client, p["leader"]["email"], "NewPass123")


def test_admin_reset_token_flow(client, ah, db):
    p, lh = register_team(client)
    uid = client.get(f"{API}/auth/me", headers=lh).json()["id"]
    tok = client.post(f"{API}/admin/users/{uid}/reset-token", headers=ah).json()["token"]
    r = client.post(f"{API}/auth/password-reset/confirm", json={"token": tok, "new_password": "Reset12345"})
    assert r.status_code == 200
    assert client.post(f"{API}/auth/password-reset/confirm", json={"token": tok, "new_password": "Again12345"}).status_code == 400
    login(client, p["leader"]["email"], "Reset12345")
