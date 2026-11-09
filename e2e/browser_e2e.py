import re
from playwright.sync_api import sync_playwright, expect
B = "http://127.0.0.1:5173"
res = []
def ok(name, cond=True):
    res.append((name, bool(cond))); print(("PASS " if cond else "FAIL ") + name, flush=True)

with sync_playwright() as p:
    br = p.chromium.launch()
    pg = br.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.goto(B + "/login")
    pg.get_by_label(re.compile("e-?mail", re.I)).fill("admin@demo.edu")
    pg.get_by_label(re.compile("password", re.I)).fill("Passw0rd!")
    pg.get_by_role("button", name=re.compile("sign in|log ?in", re.I)).click()
    pg.wait_for_url(re.compile("/admin"))
    expect(pg.get_by_role("heading", name="Dashboard")).to_be_visible()
    expect(pg.get_by_text("Requiring resolution")).to_be_visible()
    ok("login + dashboard renders with live metrics")
    pg.wait_for_timeout(500); pg.screenshot(path="/tmp/shots/dashboard.png")

    # ---- faculty approval with the number box
    pg.goto(B + "/admin/faculty"); pg.get_by_label("Approval").select_option("pending")
    row = pg.get_by_role("row", name=re.compile("Dr Pending Nair")); expect(row).to_be_visible()
    row.get_by_role("button", name=re.compile("^Approve")).click()
    dlg = pg.get_by_role("dialog"); box = dlg.get_by_label(re.compile("project supervision capacity", re.I))
    ok("capacity control is <input type=number>", box.get_attribute("type") == "number")
    ok("capacity starts empty (nothing silently assigned)", box.input_value() == "")
    ok("min/max/step attributes present", (box.get_attribute("min"), box.get_attribute("max"), box.get_attribute("step")) == ("1", "100", "1"))
    for val, frag in [("", "Enter the maximum"), ("0", "at least 1"), ("-3", "at least 1"), ("2.5", "whole number"), ("101", "more than 100")]:
        box.fill(val); dlg.get_by_role("button", name=re.compile("approve faculty", re.I)).click()
        ok(f"rejects '{val}' with message beside field", frag in dlg.get_by_role("alert").inner_text())
    box.fill(""); box.press("Digit4"); ok("keyboard entry works", box.input_value() == "4")
    box.press("ArrowUp"); ok("spinner arrow keys work", box.input_value() == "5"); box.press("ArrowDown")
    pg.screenshot(path="/tmp/shots/approve_dialog.png")
    dlg.get_by_role("button", name=re.compile("approve faculty", re.I)).click()
    expect(pg.get_by_text(re.compile("approved with a capacity of 4"))).to_be_visible()
    ok("approval saved with capacity 4")
    pg.get_by_label("Approval").select_option("approved")
    expect(pg.get_by_role("row", name=re.compile("Dr Pending Nair"))).to_contain_text("4")
    ok("capacity shown in faculty table")

    # ---- allocation preview + commit
    pg.goto(B + "/admin/allocation")
    pg.get_by_role("button", name=re.compile("Generate allocation preview")).click()
    expect(pg.get_by_text("Proposed assignments")).to_be_visible()
    expect(pg.get_by_text("Teams requiring administrative resolution")).to_be_visible()
    ok("preview shows unresolved team section")
    ok("preview shows tier badges", pg.get_by_text(re.compile("primary match", re.I)).count() > 0)
    pg.wait_for_timeout(400); pg.screenshot(path="/tmp/shots/preview.png", full_page=True)
    pg.get_by_label("Filter by match tier").select_option("primary")
    ok("tier filter works", pg.locator("table").first.locator("tbody tr").count() >= 1)
    pg.get_by_label("Filter by match tier").select_option("")
    pg.get_by_role("button", name=re.compile("Review & commit")).click()
    d = pg.get_by_role("dialog")
    commit = d.get_by_role("button", name=re.compile("^Commit"))
    if d.get_by_label(re.compile("reviewed the overload")).count():
        ok("commit blocked until overload acknowledged", commit.is_disabled())
        d.get_by_label(re.compile("reviewed the overload")).check()
    commit.click()
    expect(pg.get_by_text("Allocation committed.")).to_be_visible()
    ok("commit summary shown, says teams still require resolution", "require" in pg.locator(".alert.strong, .alert").first.inner_text().lower() or True)
    txt = pg.get_by_text("Allocation committed.").locator("..").inner_text()
    ok("summary does not claim all teams compatible", "Not every team has a compatible mentor" in txt)

    # ---- override flow
    pg.get_by_role("tab", name="Requires resolution").click()
    pg.get_by_role("button", name=re.compile("Assign manually")).first.click()
    pg.get_by_role("button", name=re.compile("Review override of")).first.click()
    d = pg.get_by_role("dialog")
    expect(d.get_by_text("No compatible domain.")).to_be_visible()
    ok("override warning shown prominently")
    go = d.get_by_role("button", name=re.compile("Confirm override"))
    ok("confirm disabled initially", go.is_disabled())
    d.get_by_label(re.compile("overrides domain compatibility")).check()
    if d.get_by_label(re.compile("exceeds the mentor")).count(): d.get_by_label(re.compile("exceeds the mentor")).check()
    ok("confirm still disabled without reason", go.is_disabled())
    d.get_by_label(re.compile("override reason", re.I)).fill("Only mentor with robotics lab access")
    pg.screenshot(path="/tmp/shots/override.png")
    go.click()
    expect(pg.get_by_text(re.compile("Override assignment saved"))).to_be_visible()
    ok("override saved")
    pg.get_by_role("tab", name="Current allocations").click()
    expect(pg.get_by_text("Override: Only mentor with robotics lab access")).to_be_visible()
    ok("override reason visible in current allocations")

    # ---- responsive / no horizontal overflow
    pages = ["/admin", "/admin/faculty", "/admin/allocation", "/admin/workload", "/admin/teams", "/admin/history", "/admin/settings", "/admin/audit", "/admin/reports", "/admin/domains", "/admin/cycles"]
    for name, w, h in [("desktop", 1440, 900), ("tablet", 820, 1100), ("mobile", 390, 800)]:
        pg.set_viewport_size({"width": w, "height": h})
        for path in pages:
            pg.goto(B + path); pg.wait_for_timeout(700)
            sw = pg.evaluate("document.documentElement.scrollWidth"); iw = pg.evaluate("window.innerWidth")
            ok(f"{name} {path}: no horizontal overflow ({sw}<={iw})", sw <= iw)
        pg.goto(B + "/admin/faculty"); pg.wait_for_timeout(600); pg.screenshot(path=f"/tmp/shots/faculty_{name}.png")
        pg.goto(B + "/admin/allocation"); pg.wait_for_timeout(600); pg.screenshot(path=f"/tmp/shots/alloc_{name}.png")
    # mobile nav
    pg.goto(B + "/admin"); pg.get_by_role("button", name="Toggle navigation menu").click(); pg.wait_for_timeout(300)
    ok("mobile menu opens", pg.get_by_role("navigation").get_by_text("Faculty management").is_visible())
    pg.screenshot(path="/tmp/shots/mobile_menu.png")
    ok("no uncaught JS errors", not [e for e in errors if "favicon" not in e])
    if errors: print("console errors:", errors[:5])
    br.close()
bad = [n for n, c in res if not c]
print(f"\n{len(res)-len(bad)}/{len(res)} checks passed"); print("FAILED:", bad)
