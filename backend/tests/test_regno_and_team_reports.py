"""Register-number validation and the Team Composition / Team-Mentor reports."""
import io

import pytest

from app.services.common import validate_regno

from .helpers import API, admin_headers, new_cycle, register_team, team_payload

@pytest.fixture
def ah(client):
    h = admin_headers(client)
    new_cycle(client, h)
    return h


VALID = ["RA2311003040001", "RA2411003040001", "RA2511003040010", "RA2611003040025", "RA9911003040999", "ra2311003040002"]
INVALID = ["", "REG0001", "RA2311003040000", "RA231100304001", "RA23110030400011", "RB2311003040001",
           "RA2311003050001", "RA2A11003040001", "2311003040001", "RA2311003040O01"]


@pytest.mark.parametrize("v", VALID)
def test_valid_register_numbers(v):
    assert validate_regno(v) == v.upper()


@pytest.mark.parametrize("v", INVALID)
def test_invalid_register_numbers(v):
    with pytest.raises(ValueError):
        validate_regno(v)


def test_registration_rejects_bad_register_number_with_clear_message(client, ah):
    p = team_payload()
    p["members"][0]["registration_number"] = "REG0001"
    r = client.post(f"{API}/register/team", json=p)
    assert r.status_code == 422 and "RA{BATCH}11003040{NNN}" in str(r.json()["detail"])


def test_future_batches_accepted(client, ah):
    p = team_payload()
    p["leader"]["registration_number"] = "RA3011003040001"
    p["members"][0]["registration_number"] = "RA3111003040002"
    p["members"][1]["registration_number"] = "RA4511003040003"
    assert client.post(f"{API}/register/team", json=p).status_code == 201


def test_report_json_matches_downloads(client, ah):
    p, _ = register_team(client, size=3)
    comp = client.get(f"{API}/admin/reports/team-composition", headers=ah).json()
    t = next(x for x in comp["teams"] if x["team_name"] == p["team_name"])
    assert t["members"][0]["is_leader"] and len(t["members"]) == 3 and t["lead_registration_number"] == p["leader"]["registration_number"]
    assert len({x["team_id"] for x in comp["teams"]}) == len(comp["teams"])
    men = client.get(f"{API}/admin/reports/team-mentor", headers=ah).json()
    row = next(x for x in men["rows"] if x["team_name"] == p["team_name"])
    assert row["mentor_name"] == "Not Assigned" and not row["assigned"]
    for path in ("team-composition", "team-mentor"):
        pdf = client.get(f"{API}/admin/reports/{path}?format=pdf", headers=ah)
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
        xl = client.get(f"{API}/admin/reports/{path}?format=xlsx", headers=ah)
        assert xl.status_code == 200 and xl.content[:2] == b"PK"
    import openpyxl
    ws = openpyxl.load_workbook(io.BytesIO(client.get(f"{API}/admin/reports/team-mentor?format=xlsx", headers=ah).content)).active
    assert any(p["team_name"] in (c or "") for r in ws.iter_rows(values_only=True) for c in r if isinstance(c, str))
    assert client.get(f"{API}/admin/reports/team-mentor?format=csv", headers=ah).status_code == 422


def test_reports_require_admin(client):
    assert client.get(f"{API}/admin/reports/team-composition").status_code in (401, 403)
    assert client.get(f"{API}/admin/reports/team-mentor").status_code in (401, 403)
