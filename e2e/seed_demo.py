import sys, httpx
sys.path.insert(0, "/home/claude/Project_Guide_Allocation/backend")
from tests.helpers import *
from scripts.create_admin import create_admin
from app.database import SessionLocal
c = httpx.Client(base_url="http://127.0.0.1:8000", timeout=30)
with SessionLocal() as db: create_admin(db, "admin@demo.edu", "Demo Admin", PW)
r = c.post(f"{API}/auth/login", json={"email": "admin@demo.edu", "password": PW}); ah = {"Authorization": "Bearer " + r.json()["access_token"]}
new_cycle(c, ah, "2026-27")
CY, IOT, ROB, ML, AI = "Cybersecurity", "Internet of Things", "Robotics", "Machine Learning", "Artificial Intelligence"
make_faculty(c, ah, "Dr Cyber Sharma", [CY], cap=2)
make_faculty(c, ah, "Dr Iot Menon", [IOT], cap=5)
make_faculty(c, ah, "Dr Ai Iyer", [AI], cap=3)
make_faculty(c, ah, "Dr Pending Nair", [CY, IOT], cap=4, approve=False)
for i in range(3): approved_team(c, ah, CY, interests=[IOT])
approved_team(c, ah, ML); approved_team(c, ah, AI); approved_team(c, ah, ROB)
print("seeded")
