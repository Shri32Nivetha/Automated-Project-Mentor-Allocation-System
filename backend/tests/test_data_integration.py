import os

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import (Allocation, AllocationCycle, Domain, FacultyProfile, Team, TeamDomain, TeamMember, User)
from scripts.create_admin import create_admin
from scripts.seed import seed
from tests.helpers import (API, PW, admin_headers, approved_team, make_faculty, new_cycle, preview_and_commit,
                           register_team)


@pytest.fixture
def ah(client):
    h = admin_headers(client)
    new_cycle(client, h)
    return h


def test_database_constraints(client, db, ah):
    register_team(client, name="T1")
    register_team(client, name="T2")
    t1, t2 = db.scalars(select(Team).order_by(Team.id)).all()
    m = t1.members[0]
    db.add(TeamMember(team_id=t2.id, cycle_id=t2.cycle_id, full_name="Dup", email="unique@x.edu",
                      registration_number=m.registration_number, department="CSE", programme="B.Tech"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.add(TeamMember(team_id=t2.id, cycle_id=t2.cycle_id, full_name="Dup", email=m.email, registration_number="RA2611003040901",
                      department="CSE", programme="B.Tech"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.add(TeamDomain(team_id=t1.id, domain_id=1, kind="primary"))
    db.flush()
    db.add(TeamDomain(team_id=t1.id, domain_id=1, kind="interest"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.add(AllocationCycle(name="second-active", academic_year="2030", status="active", active_marker=1))
    with pytest.raises(IntegrityError):                       # only one active cycle can exist
        db.commit()
    db.rollback()


def test_unique_allocation_per_team_and_cycle_and_employee_id(client, db, ah):
    a = make_faculty(client, ah, "Dr One", ["Cybersecurity"], cap=3)
    t = approved_team(client, ah, "Cybersecurity")
    preview_and_commit(client, ah)
    al = db.scalar(select(Allocation))
    db.add(Allocation(cycle_id=al.cycle_id, team_id=al.team_id, faculty_id=al.faculty_id, assigned_by=1))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    f = db.scalar(select(FacultyProfile))
    db.add(FacultyProfile(user_id=1, employee_id=f.employee_id, department="x", designation="y"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_migrations_match_models_and_head_applied():
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    with engine.connect() as c:
        ctx = MigrationContext.configure(c, opts={"compare_type": True})
        assert ctx.get_current_revision() == head
        assert compare_metadata(ctx, Base.metadata) == []      # no drift between models and migrations


def test_seed_is_repeatable_and_keeps_admin_changes(db):
    total = db.scalar(select(func.count()).select_from(Domain))
    assert total >= 50 and db.scalar(select(func.count()).select_from(Domain).where(Domain.is_other == True)) == 1  # noqa
    d = db.scalar(select(Domain).where(Domain.name == "Robotics"))
    d.name, d.is_active = "Robotics & Mechatronics", False
    db.commit()
    seed(db)
    seed(db)
    assert db.scalar(select(func.count()).select_from(Domain)) == total + 1     # re-adds nothing but the renamed original
    again = db.get(Domain, d.id)
    assert again.name == "Robotics & Mechatronics" and again.is_active is False
    names = [n for (n,) in db.execute(select(Domain.name))]
    assert len(names) == len({n.lower() for n in names})


def test_required_domains_present(db):
    required = ["Artificial Intelligence", "Generative AI", "Digital Forensics", "Natural Computing", "Speech Processing",
                "Educational Technology", "Other", "Software Testing and Quality Assurance", "Geographic Information Systems"]
    names = {n for (n,) in db.execute(select(Domain.name))}
    assert set(required) <= names


def test_cors_allows_vite_origin_only(client):
    ok = client.options(f"{API}/auth/login", headers={"Origin": "http://localhost:5173",
                                                      "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options(f"{API}/auth/login", headers={"Origin": "http://evil.example",
                                                       "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers


def test_database_url_handles_special_characters():
    s = Settings(db_user="u@ser", db_password="p@ss:w/ord#%&", jwt_secret="x" * 40, _env_file=None)
    assert s.database_url.password == "p@ss:w/ord#%&"
    assert "p@ss:w/ord#%&" not in str(s.database_url)             # hidden in repr
    assert s.database_url.drivername == "mysql+pymysql"


def test_invalid_jwt_secret_rejected():
    with pytest.raises(Exception):
        Settings(jwt_secret="change-me", _env_file=None)
    with pytest.raises(Exception):
        Settings(jwt_secret="short", _env_file=None)


def test_engine_is_mysql_family():
    assert engine.dialect.name in ("mysql", "mariadb")
    with engine.connect() as c:
        assert c.execute(text("select @@character_set_database")).scalar() == "utf8mb4"


def test_admin_bootstrap_rules(db):
    create_admin(db, "Boss@College.edu", "Boss", PW)
    with pytest.raises(ValueError):
        create_admin(db, "boss@college.edu", "Boss", PW)
    with pytest.raises(ValueError):
        create_admin(db, "weak@college.edu", "Weak", "short")
    assert db.scalar(select(User).where(User.email == "boss@college.edu")).role == "admin"


def test_api_validation_errors_are_structured(client, ah):
    r = client.post(f"{API}/register/team", json={"team_name": "x"})
    assert r.status_code == 422 and r.json()["detail"]["errors"]
    p = {"full_name": "Dr X", "email": "not-an-email", "employee_id": "E1", "department": "CSE", "designation": "Professor",
         "password": "weak", "expertise_domain_ids": [1], "requested_capacity": 2}
    assert client.post(f"{API}/register/faculty", json=p).status_code == 422


def test_reports_csv_admin_only_and_safe(client, ah):
    p, lh = register_team(client, name="=cmd|calc")
    assert client.get(f"{API}/admin/reports/registrations", headers=lh, params={"format": "csv"}).status_code == 403
    assert client.get(f"{API}/admin/reports/registrations", params={"format": "csv"}).status_code == 401
    t = client.get(f"{API}/team", headers=lh).json()
    client.put(f"{API}/admin/teams/{t['id']}/members/{t['members'][1]['id']}", headers=ah,
               json={"full_name": "Zoë Müller, Jr."})
    r = client.get(f"{API}/admin/reports/registrations", headers=ah, params={"format": "csv"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    body = r.content.decode("utf-8-sig")
    assert '"Zoë Müller, Jr."' in body            # special characters + comma quoted correctly
    assert "'=cmd|calc" in body                     # formula injection neutralised
    for name in ("teams-by-domain", "proposal-status", "faculty-workload", "faculty-capacity", "allocations",
                 "unallocated", "allocation-history"):
        assert client.get(f"{API}/admin/reports/{name}", headers=ah, params={"format": "csv"}).status_code == 200
    assert client.get(f"{API}/admin/reports/nope", headers=ah).status_code == 404


def test_dashboard_uses_real_data(client, ah):
    make_faculty(client, ah, "Dr Real", ["Cybersecurity"], cap=4)
    make_faculty(client, ah, "Dr Wait", ["Cybersecurity"], cap=2, approve=False)
    approved_team(client, ah, "Cybersecurity")
    register_team(client)
    preview_and_commit(client, ah)
    d = client.get(f"{API}/admin/dashboard", headers=ah).json()
    assert d["total_teams"] == 2 and d["allocated_teams"] == 1 and d["unallocated_teams"] == 1
    assert d["pending_faculty_approvals"] == 1 and d["eligible_faculty"] == 1
    assert d["total_capacity"] == 4 and d["remaining_capacity"] == 3
    assert d["domain_team_counts"] == [{"domain": "Cybersecurity", "teams": 1}]
    assert d["recent_actions"]


def test_notifications_are_private_and_markable(client, ah):
    _, h1 = register_team(client)
    _, h2 = register_team(client)
    n = client.get(f"{API}/notifications", headers=h1).json()["items"][0]
    assert client.post(f"{API}/notifications/{n['id']}/read", headers=h2).status_code == 404
    before = client.get(f"{API}/notifications/unread-count", headers=h1).json()["unread"]
    assert client.post(f"{API}/notifications/{n['id']}/read", headers=h1).status_code == 200
    assert client.get(f"{API}/notifications/unread-count", headers=h1).json()["unread"] == before - 1
    client.post(f"{API}/notifications/read-all", headers=h1)
    assert client.get(f"{API}/notifications/unread-count", headers=h1).json()["unread"] == 0


def test_existing_leader_can_register_in_new_cycle_but_not_steal_account(client, ah):
    p, _ = register_team(client)
    new_cycle(client, ah, "2027-28")
    again = {**p, "team_name": "Next Year Team"}
    again["members"] = [{**m, "email": "n" + m["email"], "registration_number": "RA24" + m["registration_number"][4:]} for m in p["members"]]
    r = client.post(f"{API}/register/team", json=again)
    assert r.status_code == 201
    bad = {**again, "team_name": "Thief", "leader": {**p["leader"], "password": "Wrongpass99",
                                                    "registration_number": "RA2711003040902"}}
    bad["members"] = [{**m, "email": "x" + m["email"], "registration_number": "RA25" + m["registration_number"][4:]} for m in p["members"]]
    assert client.post(f"{API}/register/team", json=bad).status_code == 409
