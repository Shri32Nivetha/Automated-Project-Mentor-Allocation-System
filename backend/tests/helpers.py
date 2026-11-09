import itertools

from app.database import SessionLocal
from scripts.create_admin import create_admin

_n = itertools.count(1)
API = "/api/v1"
PW = "Passw0rd!"


def hdr(token):
    return {"Authorization": f"Bearer {token}"}


def login(client, email, password=PW):
    r = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return hdr(r.json()["access_token"])


def admin_headers(client):
    with SessionLocal() as db:
        create_admin(db, f"admin{next(_n)}@college.edu", "Admin", PW)
        email = db.execute(__import__("sqlalchemy").text("select email from users where role='admin' order by id desc limit 1")).scalar()
    return login(client, email)


def new_cycle(client, ah, name="2026-27", **extra):
    r = client.post(f"{API}/admin/cycles", headers=ah, json={"name": name, "academic_year": name, **extra})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    r = client.post(f"{API}/admin/cycles/{cid}/activate", headers=ah)
    assert r.status_code == 200, r.text
    return cid


def domain_ids(client):
    return {d["name"]: d["id"] for d in client.get(f"{API}/domains").json()}


def member(i, dept="CSE", prog="B.Tech"):
    return {"full_name": f"Student {i}", "email": f"student{i}@srmist.edu.in", "registration_number": f"RA2311003040{i % 999 + 1:03d}",
            "department": dept, "programme": prog, "year_semester": "Year 4"}


def team_payload(name=None, size=3, dept="CSE", prog="B.Tech"):
    base = next(_n) * 10
    leader = {**member(base, dept, prog), "password": PW}
    return {"team_name": name or f"Team {base}", "department": dept, "programme": prog, "year_semester": "Year 4",
            "number_of_members": size, "leader": leader,
            "members": [member(base + k, dept, prog) for k in range(1, size)]}


def register_team(client, **kw):
    p = team_payload(**kw)
    r = client.post(f"{API}/register/team", json=p)
    assert r.status_code == 201, r.text
    return p, login(client, p["leader"]["email"])


def make_faculty(client, ah, name, expertise, cap=3, dept="CSE", approve=True, supported=(), interests=(),
                 available=True, designation="Professor"):
    ids = domain_ids(client)
    n = next(_n)
    p = {"full_name": name, "email": f"fac{n}@srmist.edu.in", "employee_id": f"EMP{n:04d}", "department": dept,
         "designation": designation, "password": PW, "expertise_domain_ids": [ids[d] for d in expertise],
         "supported_domain_ids": [ids[d] for d in supported], "interest_domain_ids": [ids[d] for d in interests],
         "is_available": available, "requested_capacity": cap}
    r = client.post(f"{API}/register/faculty", json=p)
    assert r.status_code == 201, r.text
    fid = r.json()["faculty_id"]
    if approve:
        r = client.post(f"{API}/admin/faculty/{fid}/approve", headers=ah, json={"capacity": cap})
        assert r.status_code == 200, r.text
    return {"id": fid, "email": p["email"], "headers": login(client, p["email"])}


def approved_team(client, ah, domain, interests=(), dept="CSE", size=2, name=None):
    ids = domain_ids(client)
    p, lh = register_team(client, size=size, dept=dept, name=name)
    r = client.put(f"{API}/team/proposal", headers=lh, json={
        "title": f"Project for {p['team_name']}", "description": "A sufficiently long project description for testing.",
        "primary_domain_id": ids[domain], "interest_domain_ids": [ids[i] for i in interests], "technologies": ["Python"]})
    assert r.status_code == 200, r.text
    r = client.post(f"{API}/team/proposal/submit", headers=lh)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r = client.post(f"{API}/admin/proposals/{pid}/review", headers=ah, json={"action": "approve"})
    assert r.status_code == 200, r.text
    team = client.get(f"{API}/team", headers=lh).json()
    return {"id": team["id"], "proposal_id": pid, "headers": lh, "payload": p}


def preview_and_commit(client, ah, ack=True, **opts):
    r = client.post(f"{API}/admin/allocation/preview", headers=ah, json=opts)
    assert r.status_code == 201, r.text
    pv = r.json()
    r = client.post(f"{API}/admin/allocation/preview/{pv['id']}/commit", headers=ah,
                    json={"confirm": True, "acknowledge_overload": ack})
    return pv, r
