# Project Guide Allocation System (MySQL · FastAPI · React)

Team-based project guide allocation for a college. **One team registers through one form; only the team leader gets a login.**
One team receives **one** faculty guide per allocation cycle. Faculty capacity is counted in **team projects**, not students.
Allocation is **deterministic and rule-based** — no machine learning, no AI services.

* Backend: Python, FastAPI, SQLAlchemy 2.x, Pydantic, **MySQL (PyMySQL)**, Alembic, JWT, bcrypt
* Frontend: React 18, Vite, React Router
* Database name: `project_guide_allocation` (there is deliberately **no SQLite fallback**)

> This project was rebuilt from the supplied starter (which used per-student accounts and SQLite). Its idea of
> admin/faculty/student roles, domains, capacity and CSV reports was kept; the data model, API, UI and workflow are new.

---
## 1. Windows setup (PowerShell), step by step

### 1.1 Install Python
Download **Python 3.11 or 3.12** from <https://www.python.org/downloads/windows/> (tick *Add python.exe to PATH*). Then:
```powershell
python --version      # should print Python 3.11.x or 3.12.x
```
### 1.2 Install Node.js
Install the LTS version from <https://nodejs.org/>. Then:
```powershell
node --version ; npm --version
```
### 1.3 Install MySQL Server (8.x)
Run the *MySQL Installer* from <https://dev.mysql.com/downloads/installer/>, choose **MySQL Server 8.x** (and optionally **MySQL Workbench**),
and set a root password you will remember. Check the service is running:
```powershell
Get-Service MySQL*          # Status should be Running
```
### 1.4 Create the databases and an application user
Open the MySQL shell (`mysql -u root -p`, or a Workbench query tab) and run (change the password!):
```sql
CREATE DATABASE project_guide_allocation      CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE project_guide_allocation_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'pga_user'@'localhost' IDENTIFIED BY 'Choose-A-Strong-Password!';
GRANT ALL PRIVILEGES ON project_guide_allocation.*      TO 'pga_user'@'localhost';
GRANT ALL PRIVILEGES ON project_guide_allocation_test.* TO 'pga_user'@'localhost';
FLUSH PRIVILEGES;
```
(The `_test` database is used only by the automated tests; they refuse to run against any database whose name does not end in `_test`.)

### 1.5 Open the project in VS Code
```powershell
cd path\to\Project_Guide_Allocation
code .
```
Use the integrated terminal (**Terminal → New Terminal**, PowerShell).

### 1.6 Backend: virtual environment and dependencies
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
# If activation is blocked:  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass   then activate again
python -m pip install --upgrade pip
pip install -r requirements.txt
```
### 1.7 Configure `.env`
```powershell
Copy-Item .env.example .env
notepad .env
```
Set `DB_USER`, `DB_PASSWORD` (write it exactly as typed — special characters are fine), and a `JWT_SECRET`. Generate a secret with:
```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```
### 1.8 Create the tables — *schema migrations*
```powershell
alembic upgrade head
```
### 1.9 Load the domain catalogue — *seed data*
```powershell
python -m scripts.seed
```
Safe to run any number of times: it only inserts what is missing and never overwrites changes an admin made.
### 1.10 Create the first administrator — *admin bootstrap*
```powershell
python -m scripts.create_admin --email admin@yourcollege.edu --name "Your Name"
```
You are asked for a password (hidden). There is **no default admin** and **no public admin registration page**; this command is the only way to create an admin.

> **Migrations vs seed vs admin:** *migrations* create/alter the table structure; *seed* fills lookup data (domains, default settings);
> *create_admin* creates one login. They are independent: re-running seed never touches users, and migrations never delete data.

### 1.11 Start the backend
```powershell
uvicorn app.main:app --reload --port 8000
```
API docs: <http://127.0.0.1:8000/docs> · health: <http://127.0.0.1:8000/health>

### 1.12 Frontend (new terminal)
```powershell
cd frontend
npm install
Copy-Item .env.example .env        # VITE_API_URL=http://127.0.0.1:8000/api/v1
npm run dev
```
Open <http://localhost:5173> (the Vite dev server). `CORS_ORIGINS` in the backend `.env` already allows `localhost:5173` and `127.0.0.1:5173`.

### 1.13 First run: log in and try each role
1. Sign in as the **admin** → **Academic cycles → New cycle → Activate** (teams cannot register until a cycle is active).
2. **System settings**: review team-size limits (default 2–4, leader counts) and cross-department rules.
3. Open `/register/faculty`, register one or more faculty → admin **Faculty management** → open one → **Approve** (set capacity).
4. Open `/register/team`, register a team → sign in as that **team leader** → *Project proposal* → fill in, **Save & submit**.
5. Admin **Proposal review** → open → **Approve** (this marks the team eligible).
6. Admin **Workload management** to see baseline / capacity / shortage → **Guide allocation → Generate preview → Review & commit**.
7. Optionally use *Manual / reassign*, then **Finalise** and **Reports** (CSV export).

### 1.14 Run the automated tests
```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest -q
```
Optional: `$env:TEST_DB_NAME="my_other_test"` to use another `*_test` database. Frontend: `cd frontend; npm install; npm test` (Vitest component tests) and `npm run build`.
After pulling this update run `pip install -r requirements.txt` (adds `ortools`), `alembic upgrade head`, and `python -m scripts.seed` (adds the new capacity-limit settings).

---
## 2. How the rules work

### Team registration
Leader + other members are saved in `teams` / `team_members` (relational rows); only the leader gets a `users` row (role `team_leader`).
Registration numbers are normalised (spaces removed, upper-case), e-mails lower-cased. Unique keys on `(cycle, registration_number)` and `(cycle, email)`
make it impossible for a student to be in two teams in one cycle. Size limits, cross-department/programme rules and allowed e-mail domains come from **System settings**.
A leader who already has an account can register a *new* team in a *new* cycle by proving the password.

Leader edits are allowed while the proposal is `draft`/`needs_revision` and before the cycle's proposal deadline. After submission everything locks; after finalisation
membership changes require an admin (the leader submits a *change request*; the admin applies the correction, audited).

### Proposal statuses
`draft → submitted → under_review → approved | needs_revision | rejected → allocated → finalised`.
**Eligible for allocation** = status `approved` **and** the eligibility flag set (approval sets it; admin can toggle it). Rejected / unreviewed / revision-needed teams are never allocated.

### Capacity & workload (admin → Workload management)
* Capacity = max **team projects** in a cycle; stored per faculty per cycle (`faculty_cycle_capacity`), defaulting to the profile value (`faculty_profiles.max_capacity`). **No new column was needed.**
* **Setting capacity at approval:** the approval dialog has a real `<input type="number" min max step="1">` labelled *Project supervision capacity*. It starts **empty** (nothing is silently assigned);
  quick-fill buttons offer the faculty member's requested value and the designation default. The value must be a **whole number between `min_faculty_capacity` (default 1) and `max_faculty_capacity` (default 100)**
  (both editable in *System settings*; `0` is rejected by default because it would approve a mentor who can never receive a team). Decimals, text, booleans, negatives and out-of-range values are rejected **by the server**
  (`422` with a field-level message shown beside the input) as well as in the browser — both use the same rule (`services/workload.validate_capacity`, mirrored by `validateWholeNumber` in `ui.jsx`).
  Approval saves the capacity to the profile **and** the active cycle's capacity row (what the optimiser reads) and logs a `capacity_changes` row, in one transaction under a row lock. Approving twice returns `409`.
* Editing capacity later (faculty detail or *Workload management*) uses the same validation, an optimistic-concurrency check (`expected_capacity`) and requires a reason.
* **Reducing capacity below current assignments** shows a live warning (assigned count and resulting overload) and needs an explicit acknowledgement. **Existing teams are never removed or reassigned.**
* Designation defaults (HOD 5, Project coordinator 6, regular 10) are only **editable suggestions**; the admin-set value always wins.
* **Baseline** = eligible *unallocated* teams ÷ eligible faculty; a planning estimate, **not a quota**. **Shortage** = unallocated eligible teams − available capacity.
* Capacity is a **nominal** limit. If demand exceeds it, every team that has a compatible mentor is still allocated and the unavoidable **overload** (`max(0, assigned − capacity)`) is spread as evenly as possible and shown before you commit.

### Allocation engine (`backend/app/services/{matching,optimizer,allocation}.py`)
The old greedy, hard-capacity assignment was replaced by a **global optimiser: Google OR-Tools CP-SAT** (dependency `ortools`, pinned in `requirements.txt`). No machine learning; it is an exact constraint solver.
*Why CP-SAT and not min-cost max-flow:* the policy needs cross-mentor objectives (worst overload, utilisation spread, sums of squares) that cannot be expressed as per-edge costs, so a flow model could only approximate them.

**Mandatory (never relaxed by the optimiser):** approved faculty · active account · marked available · capacity > 0 · department restriction (if enabled) · **a compatible domain**.

**Hierarchical domain matching** (`matching.py`)
| Tier | Rule |
|---|---|
| 1 · Primary | team's primary domain ∈ mentor's *expertise* or *supported* domains |
| 2 · Additional | no primary match, but ≥ 1 of the team's additional domains is an exact expertise/supported match (more matches rank higher) |
| 3 · Related | no exact match, but a team domain is the direct **parent/child** (`domains.parent_id`) of a mentor domain. Always labelled *related*, never *exact* |
| none | **never assigned automatically**; the team is reported as *requiring administrative resolution* |

A domain listed only as a faculty *interest* is not compatible by itself (it only adds to the secondary preference score). The legacy `min_compatibility_score` setting is kept but **no longer affects allocation**; tiers decide compatibility.

**Objective — lexicographic, one stage at a time.** Each stage optimises one objective, then its achieved value is added as a hard constraint before the next stage runs, so a lower priority can never trade away a higher one (no giant weights, no overflow risk):
1. maximise teams given a compatible mentor → 2. minimise the **worst overload** → 3. minimise **total overload** → 4. maximise **primary** matches → 5. maximise **additional** matches (⇒ related last) →
6. maximise exactly-matched domains (multi-domain mentors) → 7. maximise related matches → 8. minimise the **spread** of utilisation (load ÷ capacity) → 9. minimise peak utilisation → 10. minimise Σ utilisation² →
11. maximise the secondary preference score (expertise > supported, interests, same department) → 12–13. deterministic tie-breaks (lowest faculty id, then a fixed pairing).

*Documented trade-off:* domain-match quality (4–7) outranks balancing of **within-capacity** utilisation (8–10), so a primary-domain mentor is not bypassed merely because another mentor is less busy; overload (2–3) outranks both, so a mentor who would be pushed over capacity **is** bypassed in favour of a compatible mentor of a lower tier. Consequently a mentor who matches *more* of a team's domains can receive several teams while a less-matching mentor stays idle, as long as nobody exceeds capacity.
The result is deterministic for unchanged inputs (sorted model, fixed seed, one worker). Time budget: `ALLOCATION_SOLVER_TIME_LIMIT_SECONDS` (default 30) shared by the stages; if it expires the best plan found so far is used and the UI says it may not be optimal.
Solver timeout/failure → `504/503 solver_*` with *"No allocation was changed"*; nothing is written.

**Preview** (nothing saved) shows, per team: domains, recommended mentor, match tier, matched domains, explanation, score, current → projected workload vs capacity, overload warnings and *why an alternative mentor was chosen*; plus mentor workload bars, teams requiring resolution (with the closest mentors), search, tier/mentor/overload filters and sorting.
**Commit** locks the cycle and faculty rows (`SELECT … FOR UPDATE`), re-validates every assignment on **fresh** data (eligibility, domain compatibility, no duplicates, and that overload does not exceed what was previewed), skips anything that changed (reported), needs an explicit **overload acknowledgement** when the plan exceeds capacity, and rolls back on any error. The summary never claims every team is compatible when some still need resolution.
**Re-optimisation:** by default only teams without a guide are optimised and all existing assignments are kept (counted once as load). Options: *re-optimise automatic assignments* (not finalised) and, separately, *include manual assignments* (explicit admin choice). Finalised allocations are never touched.

### Administrator override (Guide allocation → Manual / reassign)
Any *otherwise eligible* faculty member can be assigned by an admin, even without a compatible domain or beyond capacity. The dialog shows the team's domains next to the mentor's expertise, current → projected workload and projected overload,
a prominent warning, a **mandatory reason** (for overrides and reassignments) and explicit acknowledgement checkboxes. Mandatory rules (approved/active/available, department restriction) **cannot** be overridden. Admin-only (`403` for faculty/leaders).
Recorded in `allocation_history` (`is_override`, `domain_violation`, `capacity_violation`, `projected_load`, `capacity_at_time`, `details` incl. the **original automatic recommendation**), on the allocation (`match_tier`, `override_reason`, `auto_recommendation`) and in the audit log. Manual assignments are protected from automatic runs unless the admin opts in.
**Finalise** re-validates, requires explicit acknowledgement if any mentor is over capacity, then freezes. Afterwards automatic re-runs are disabled; only an audited manual reassignment with a reason can change a team.

### Schema change (migration `0002_allocation_optimizer_and_overrides`)
Only nullable/defaulted columns are added (existing rows are untouched): `allocations.{match_tier, matched_domains, is_override, override_reason, auto_recommendation}` and `allocation_history.{is_override, domain_violation, capacity_violation, projected_load, capacity_at_time, details}`. New settings `min_faculty_capacity`, `max_faculty_capacity` come from `python -m scripts.seed` (and fall back to defaults if it has not been re-run). Roll back with `alembic downgrade 0001`.

### Cycles
Each team, allocation, capacity row and history entry belongs to a cycle. Activating a new cycle never alters old ones; allocation runs only consider the selected cycle's teams.
Dashboards/workload/reports have a cycle selector for historical views.

### Custom domains ("Other")
Choosing **Other** requires a custom name. It is stored in `domains` (`is_custom`, status `pending`, parent = Other), linked to the team/faculty, hidden from public lists and shown in **Domain management** for approve / reject / **map to an existing domain** (sets the parent so matching follows it).

### Notifications & e-mail
In-app notifications (unread count, mark read) are database-backed. **E-mail is optional**: set `SMTP_*` in `.env` to enable password-reset e-mails. Without SMTP nothing is sent
(the UI says so); an admin can issue a one-time reset token for a user (`POST /admin/users/{id}/reset-token`) and hand it over.

### Security notes
bcrypt hashing, JWT with configurable expiry (role/active flag/token-version are read from the DB on every request), backend role checks on every route, ownership derived from the token,
`extra="forbid"` request schemas (no mass assignment), ORM-parameterised SQL, in-process login rate limiting (single-process only), generic error messages (details only in server logs), configurable CORS.

---
## 3. Troubleshooting
| Problem | Fix |
|---|---|
| `Can't connect to MySQL server` / `2003` | Start the service (`Get-Service MySQL*`, `Start-Service MySQL80`), check `DB_HOST`/`DB_PORT`. |
| `Access denied for user` / `1045` | Wrong `DB_USER`/`DB_PASSWORD`, or the user lacks grants (re-run the `GRANT` lines). |
| Password has `@ # / : %` | Put it **unchanged** in `.env`; the app builds the URL safely. Do not URL-encode it. |
| `ModuleNotFoundError` | Activate the venv (`.\.venv\Scripts\Activate.ps1`) and `pip install -r requirements.txt`. Run commands from the `backend` folder. |
| Pydantic / SQLAlchemy import errors | You probably have older packages: `pip install --upgrade -r requirements.txt` (use a fresh venv with Python 3.11/3.12). |
| `alembic upgrade head` fails | Check the DB exists and the user may create tables. If a half-applied attempt exists in a **fresh dev** database, drop and recreate that empty database and retry. Never delete a database that holds real data. |
| Port 8000 / 5173 in use | `uvicorn app.main:app --port 8001` (then set `VITE_API_URL`); Vite uses `strictPort` — stop the other process (`Get-NetTCPConnection -LocalPort 5173`). |
| Browser shows a CORS error | Add the exact origin shown in the browser address bar to `CORS_ORIGINS`, restart the backend. |
| "Cannot reach the server" in the UI | Backend not running, or `VITE_API_URL` wrong (must end with `/api/v1`); restart `npm run dev` after editing `frontend/.env`. |
| `JWT_SECRET is missing, a placeholder…` | Set a random value ≥ 32 characters in `backend/.env`. |
| Domain lists are empty | Run `python -m scripts.seed`. |
| `create_admin` says user exists / password weak | Use another e-mail; password needs ≥ 8 chars with letters and numbers. |
| "No allocation cycle is active" | Admin → Academic cycles → create and **Activate** one. |

---
## 4. Layout
```
backend/  app/{models,schemas,security,deps,config,database}.py  app/routers/*  app/services/* (allocation, workload, teams, proposals, faculty)
          alembic/ (migrations)  scripts/{seed,create_admin}.py  tests/
frontend/ src/{api,auth,ui}  src/pages/{public,leader,faculty,admin,shared}.jsx
```
## 5. Known limitations
* Login rate limiting is in-memory (resets on restart, per process). Use a reverse proxy / shared store for multi-process deployments.
* E-mail is only sent when SMTP is configured; there is no other provider integration.
* Capacity is edited one faculty member at a time (no bulk import). Designation capacity defaults are suggestions applied by the admin at approval time.
* The UI was verified by building it and by exercising the same API it calls; it was not browser-tested on real devices here (see delivery notes).

## UI design system (frontend)
The whole interface is driven by design tokens in `frontend/src/styles.css` (navy/slate neutrals, off-white canvas, one indigo→violet accent, layered shadows, 8/12/16 px radii, a 0.75–1.55 rem type scale). Typography is **Inter**, self-hosted through the `@fontsource-variable/inter` npm package (no external CDN request; system fonts are the fallback).
Pages should compose the shared components in `frontend/src/ui.jsx` instead of styling things themselves: `PageHead`, `Card`, `Stat` (optional `icon`), `Badge` / `TierBadge`, `UtilBar`, `Alert`, `Btn`, `Field` + `NumberInput`, `MultiSelect`, `DataTable` (search, sort, filters, pagination, stacked-card layout on phones), `Modal` / `useConfirm`, `Skeleton`, `Empty`, `Tip` and toasts.
Motion is limited to short (<= 240 ms) transitions and is disabled under `prefers-reduced-motion`. Layouts are verified for desktop, tablet (820 px) and mobile (390 px) with no horizontal scrolling; tables turn into labelled cards on small screens.

## Register numbers & team reports

* **Register number format** – `RA{BATCH}11003040{NNN}` (e.g. `RA2311003040001`): `RA`, any two-digit batch, fixed code `11003040`, three-digit student number `001`-`999`. Enforced in the API (`services/common.py::validate_regno`, used by `MemberIn` and member edits) and in the forms (`frontend/src/regno.js`). Existing records are never modified; a legacy number is only checked if someone changes it. Uniqueness stays per allocation cycle (existing DB constraint).
* **Institutional e-mail** – team leaders, team members and faculty must register with an `@srmist.edu.in` address (any username; addresses are normalised first). Enforced in the API (`services/common.py::check_institutional_email`) and in the forms (`frontend/src/email.js`).
* **Reports** (Admin → Insight): *Team composition* and *Team–mentor report*, each viewable on screen with **Download PDF** / **Download Excel**. API: `GET /api/v1/admin/reports/team-composition|team-mentor?cycle_id=&format=json|pdf|xlsx`. New dependencies: `openpyxl`, `reportlab`. No schema change or migration.
