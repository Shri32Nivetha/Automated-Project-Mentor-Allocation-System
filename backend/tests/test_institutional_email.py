"""Institutional e-mail rule: only @srmist.edu.in for team leaders, team members and faculty."""
import pytest

from .helpers import API, PW, admin_headers, domain_ids, login, make_faculty, new_cycle, register_team, team_payload

@pytest.fixture
def ah(client):
    h = admin_headers(client)
    new_cycle(client, h)
    return h


BAD = ["someone@gmail.com", "someone@yahoo.com", "someone@outlook.com", "someone@college.edu", "someone@srmist.edu",
       "someone@srmist.edu.in.evil.com", "someone@mail.srmist.edu.in", "someone@notsrmist.edu.in", "srmist.edu.in",
       "@srmist.edu.in", "someone@srmist.edu.in@gmail.com", "some one@srmist.edu.in"]


def _fac_payload(client, email):
    ids = domain_ids(client)
    return {"full_name": "Dr Test", "email": email, "employee_id": "EMPX1", "department": "CSE", "designation": "Professor",
            "password": PW, "expertise_domain_ids": [next(iter(ids.values()))], "requested_capacity": 3}


def test_valid_emails_accepted_for_leader_members_and_faculty(client, ah):
    p = team_payload()
    p["leader"]["email"] = "Any.Name_1+x@SRMIST.EDU.IN "          # normalised before the domain check
    p["members"][0]["email"] = "ab1234@srmist.edu.in"
    assert client.post(f"{API}/register/team", json=p).status_code == 201
    assert login(client, "any.name_1+x@srmist.edu.in")
    make_faculty(client, ah, "Dr Valid", [next(iter(domain_ids(client)))])


@pytest.mark.parametrize("email", BAD)
def test_team_leader_rejected(client, ah, email):
    p = team_payload()
    p["leader"]["email"] = email
    r = client.post(f"{API}/register/team", json=p)
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("email", BAD)
def test_team_member_rejected(client, ah, email):
    p = team_payload()
    p["members"][0]["email"] = email
    assert client.post(f"{API}/register/team", json=p).status_code == 422


def test_external_domain_message_is_clear(client, ah):
    p = team_payload()
    p["members"][0]["email"] = "x@gmail.com"
    assert "@srmist.edu.in" in str(client.post(f"{API}/register/team", json=p).json()["detail"])


@pytest.mark.parametrize("email", BAD)
def test_faculty_rejected(client, ah, email):
    assert client.post(f"{API}/register/faculty", json=_fac_payload(client, email)).status_code == 422


def test_faculty_message_and_no_account_created(client, ah):
    r = client.post(f"{API}/register/faculty", json=_fac_payload(client, "dr@gmail.com"))
    assert r.status_code == 422 and "@srmist.edu.in" in str(r.json()["detail"])
    assert client.post(f"{API}/auth/login", json={"email": "dr@gmail.com", "password": PW}).status_code in (400, 401)


def test_member_add_and_change_enforce_domain(client, ah):
    _, lh = register_team(client, size=2)
    body = {"full_name": "Added One", "email": "a@gmail.com", "registration_number": "RA2611003040951"}
    assert client.post(f"{API}/team/members", headers=lh, json=body).status_code == 422
    assert client.post(f"{API}/team/members", headers=lh, json={**body, "email": "a@srmist.edu.in"}).status_code == 201


def test_duplicate_email_checks_still_work(client, ah):
    p1, _ = register_team(client)
    p2 = team_payload()
    p2["members"][0]["email"] = p1["members"][0]["email"].upper()
    r = client.post(f"{API}/register/team", json=p2)
    assert r.status_code == 409 and "E-mail" in r.json()["detail"]
    f = make_faculty(client, ah, "Dr Dup", [next(iter(domain_ids(client)))])
    r = client.post(f"{API}/register/faculty", json=_fac_payload(client, f["email"].upper()))
    assert r.status_code == 409
