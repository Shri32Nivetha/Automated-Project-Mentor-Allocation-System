# Real-browser end-to-end check (optional)

Drives the running app with Playwright: admin login, numeric capacity approval (valid/invalid values), allocation preview,
commit, override flow, and a no-horizontal-overflow check on 11 admin pages at desktop/tablet/mobile widths.

1. Use a **fresh dev database**: `alembic upgrade head && python -m scripts.seed`
2. Start backend (`uvicorn app.main:app --port 8000`) and frontend (`npm run dev`)
3. `python e2e/seed_demo.py` (creates admin `admin@demo.edu` / `Passw0rd!` + demo data; run from `backend/` so imports resolve)
4. `pip install playwright && playwright install chromium && python e2e/browser_e2e.py`

Never run seed_demo.py against a real database: it creates a demo admin with a known password.
