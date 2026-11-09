"""Team Composition and Team-Mentor Allocation reports.

Data comes straight from the existing tables (teams, team_members, allocations, faculty_profiles, users);
no extra tables. The same dict feeds the on-screen JSON, the PDF and the XLSX so all three always match.
"""
import io
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from fastapi import HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Allocation, AllocationCycle, Team
from .common import get_setting

NOT_ASSIGNED = "Not Assigned"
DASH = "—"
COLLEGE_TITLE = "Project Guide Allocation System"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ------------------------------------------------------------------ data
def _teams(db: Session, cyc: AllocationCycle) -> list[Team]:
    return list(db.scalars(select(Team).where(Team.cycle_id == cyc.id).order_by(Team.id)).unique())


def team_composition(db: Session, cyc: AllocationCycle) -> dict:
    min_size = int(get_setting(db, "min_team_size"))
    teams = []
    for t in _teams(db, cyc):
        seen, members = set(), []
        for m in sorted(t.members, key=lambda x: (not x.is_leader, x.id)):   # lead first, then members in join order
            if m.id in seen:
                continue
            seen.add(m.id)
            members.append({"name": m.full_name, "registration_number": m.registration_number, "is_leader": bool(m.is_leader)})
        lead = next((m for m in members if m["is_leader"]), None)
        notes = []
        if lead is None:
            notes.append("No team lead recorded")
        if len(members) < min_size:
            notes.append(f"Incomplete team: {len(members)} of minimum {min_size} members")
        teams.append({"team_id": t.id, "team_name": t.name,
                      "lead_name": lead["name"] if lead else (t.leader.full_name if t.leader else DASH),
                      "lead_registration_number": lead["registration_number"] if lead else DASH,
                      "member_count": len(members), "complete": not notes, "note": "; ".join(notes),
                      "members": members})
    return {"title": "Team Composition Report", "teams": teams, "total_teams": len(teams),
            "total_students": sum(t["member_count"] for t in teams)}


def team_mentor(db: Session, cyc: AllocationCycle) -> dict:
    allocs = {a.team_id: a for a in db.scalars(select(Allocation).where(Allocation.cycle_id == cyc.id)).unique()}
    rows = []
    for t in _teams(db, cyc):
        lead = next((m.full_name for m in t.members if m.is_leader), None) or (t.leader.full_name if t.leader else DASH)
        a = allocs.get(t.id)
        f = a.faculty if a else None
        rows.append({"team_id": t.id, "team_name": t.name, "lead_name": lead,
                     "mentor_name": f.user.full_name if f else NOT_ASSIGNED,
                     "mentor_id": f.employee_id if f else DASH,
                     "mentor_email": (f.user.email or DASH) if f else DASH,
                     "assigned": f is not None})
    return {"title": "Team–Mentor Allocation Report", "rows": rows, "total_teams": len(rows),
            "assigned_teams": sum(r["assigned"] for r in rows)}


# ------------------------------------------------------------------ response
def respond(fmt: str, data: dict, cyc: AllocationCycle, basename: str, pdf_fn, xlsx_fn):
    fmt = (fmt or "json").lower()
    meta = {"id": cyc.id, "name": cyc.name, "academic_year": cyc.academic_year}
    if fmt == "json":
        return {"cycle": meta, **data}
    stamp = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    if fmt == "pdf":
        body, media, ext = pdf_fn(data, meta, stamp), "application/pdf", "pdf"
    elif fmt == "xlsx":
        body, media, ext = xlsx_fn(data, meta, stamp), XLSX_TYPE, "xlsx"
    else:
        raise HTTPException(422, "format must be json, pdf or xlsx.")
    return Response(content=body, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{basename}_{cyc.id}.{ext}"'})


# ------------------------------------------------------------------ PDF
def _pdf_doc(buf, pagesize, title):
    from reportlab.platypus import SimpleDocTemplate
    return SimpleDocTemplate(buf, pagesize=pagesize, leftMargin=36, rightMargin=36, topMargin=64, bottomMargin=48,
                             title=title, author=COLLEGE_TITLE)


def _pdf_page_deco(title, meta, stamp):
    from reportlab.lib import colors

    def draw(canvas, doc):
        w, h = doc.pagesize
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 13)
        canvas.drawString(36, h - 34, COLLEGE_TITLE)
        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(colors.HexColor("#475569"))
        canvas.drawString(36, h - 48, f"{title}  |  Cycle: {meta['name']} ({meta['academic_year']})")
        canvas.drawRightString(w - 36, h - 34, f"Generated: {stamp}")
        canvas.setStrokeColor(colors.HexColor("#94a3b8"))
        canvas.line(36, h - 54, w - 36, h - 54)
        canvas.line(36, 38, w - 36, 38)
        canvas.drawString(36, 26, "Official record - generated from the live allocation database")
        canvas.drawRightString(w - 36, 26, f"Page {doc.page}")
        canvas.restoreState()
    return draw


def _styles():
    from reportlab.lib.styles import ParagraphStyle
    base = ParagraphStyle("c", fontName="Helvetica", fontSize=9, leading=11)
    return {"cell": base, "bold": ParagraphStyle("b", parent=base, fontName="Helvetica-Bold"),
            "head": ParagraphStyle("h", parent=base, fontName="Helvetica-Bold", textColor="white"),
            "title": ParagraphStyle("t", parent=base, fontName="Helvetica-Bold", fontSize=15, leading=19, spaceAfter=4),
            "sub": ParagraphStyle("s", parent=base, textColor="#475569", spaceAfter=10),
            "team": ParagraphStyle("tm", parent=base, fontName="Helvetica-Bold", fontSize=10.5, leading=13),
            "note": ParagraphStyle("n", parent=base, textColor="#b45309", fontName="Helvetica-Oblique")}


def _p(text, style):
    from reportlab.platypus import Paragraph
    return Paragraph(escape(str(text if text is not None else "")), style)


def composition_pdf(data, meta, stamp) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import KeepTogether, Spacer, Table, TableStyle
    st, buf = _styles(), io.BytesIO()
    doc = _pdf_doc(buf, A4, data["title"])
    flow = [_p(data["title"], st["title"]),
            _p(f"Total teams: {data['total_teams']}   |   Total students: {data['total_students']}", st["sub"])]
    if not data["teams"]:
        flow.append(_p("No teams are registered in this cycle.", st["cell"]))
    for t in data["teams"]:
        head = Table([[_p(f"Team ID {t['team_id']}  -  {t['team_name']}", st["team"]),
                       _p(f"Team Lead: {t['lead_name']} ({t['lead_registration_number']})", st["cell"])]],
                     colWidths=[250, 289])
        head.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#e2e8f0")),
                                  ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 5),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        rows = [[_p("#", st["head"]), _p("Member name", st["head"]), _p("Register number", st["head"]), _p("Role", st["head"])]]
        for i, m in enumerate(t["members"], 1):
            sty = st["bold"] if m["is_leader"] else st["cell"]
            rows.append([_p(i, sty), _p(m["name"], sty), _p(m["registration_number"], sty),
                         _p("Team Lead" if m["is_leader"] else "Member", sty)])
        tbl = Table(rows, colWidths=[28, 215, 156, 140], repeatRows=1)
        ts = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        for i, m in enumerate(t["members"], 1):
            if m["is_leader"]:
                ts.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#dbeafe")))
        tbl.setStyle(TableStyle(ts))
        block = [head, tbl]
        if t["note"]:
            block.append(_p(t["note"], st["note"]))
        block.append(Spacer(1, 12))
        flow.append(KeepTogether(block))
    deco = _pdf_page_deco(data["title"], meta, stamp)
    doc.build(flow, onFirstPage=deco, onLaterPages=deco)
    return buf.getvalue()


def mentor_pdf(data, meta, stamp) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import Table, TableStyle
    st, buf = _styles(), io.BytesIO()
    doc = _pdf_doc(buf, landscape(A4), data["title"])
    flow = [_p(data["title"], st["title"]),
            _p(f"Total teams: {data['total_teams']}   |   Mentor assigned: {data['assigned_teams']}   |   "
               f"Not assigned: {data['total_teams'] - data['assigned_teams']}", st["sub"])]
    cols = ["Team ID", "Team name", "Team lead", "Mentor name", "Mentor ID", "Mentor email"]
    rows = [[_p(c, st["head"]) for c in cols]]
    for r in data["rows"]:
        rows.append([_p(r[k], st["cell"]) for k in ("team_id", "team_name", "lead_name", "mentor_name", "mentor_id", "mentor_email")])
    tbl = Table(rows, colWidths=[48, 150, 130, 140, 80, 210], repeatRows=1)
    ts = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
          ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
          ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")])]
    for i, r in enumerate(data["rows"], 1):
        if not r["assigned"]:
            ts.append(("TEXTCOLOR", (3, i), (3, i), colors.HexColor("#b45309")))
    tbl.setStyle(TableStyle(ts))
    flow.append(tbl if data["rows"] else _p("No teams are registered in this cycle.", st["cell"]))
    deco = _pdf_page_deco(data["title"], meta, stamp)
    doc.build(flow, onFirstPage=deco, onLaterPages=deco)
    return buf.getvalue()


# ------------------------------------------------------------------ XLSX
def _safe(v):
    """Neutralise spreadsheet formula injection (same rule as the CSV exports)."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def _xlsx_frame(title, meta, stamp, ncols):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws["A1"] = f"{COLLEGE_TITLE} - {title}"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"Cycle: {meta['name']} ({meta['academic_year']})    Generated: {stamp}"
    ws["A2"].alignment = Alignment(horizontal="left")
    return wb, ws


def _xlsx_bytes(wb) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _header_row(ws, row, cols, widths):
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    thin = Side(style="thin", color="CBD5E1")
    for c, (name, w) in enumerate(zip(cols, widths), 1):
        cell = ws.cell(row=row, column=c, value=name)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1E3A8A")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
        ws.column_dimensions[cell.column_letter].width = w
    ws.row_dimensions[row].height = 22


def composition_xlsx(data, meta, stamp) -> bytes:
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    wb, ws = _xlsx_frame(data["title"], meta, stamp, 5)
    ws["A3"] = f"Total teams: {data['total_teams']}    Total students: {data['total_students']}"
    cols = ["Team ID", "Team Name", "Role", "Member Name", "Register Number"]
    _header_row(ws, 5, cols, [10, 30, 14, 34, 24])
    thin = Side(style="thin", color="CBD5E1")
    box = Border(top=thin, bottom=thin, left=thin, right=thin)
    r = 6
    for t in data["teams"]:
        ws.cell(row=r, column=1, value=f"Team {t['team_id']}: {t['team_name']}   |   Team Lead: {t['lead_name']} "
                                        f"({t['lead_registration_number']})   |   Members: {t['member_count']}"
                                        + (f"   |   {t['note']}" if t["note"] else ""))
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=5)
        for c in range(1, 6):
            ws.cell(row=r, column=c).fill = PatternFill("solid", fgColor="E2E8F0")
        ws.cell(row=r, column=1).font = Font(bold=True)
        r += 1
        for m in t["members"]:
            vals = [t["team_id"], _safe(t["team_name"]), "Team Lead" if m["is_leader"] else "Member",
                    _safe(m["name"]), _safe(m["registration_number"])]
            for c, v in enumerate(vals, 1):
                cell = ws.cell(row=r, column=c, value=v)
                cell.border = box
                cell.alignment = Alignment(horizontal="center" if c == 1 else "left", vertical="center")
                if m["is_leader"]:
                    cell.font = Font(bold=True)
                    cell.fill = PatternFill("solid", fgColor="DBEAFE")
            r += 1
    ws.freeze_panes = "A6"
    return _xlsx_bytes(wb)


def mentor_xlsx(data, meta, stamp) -> bytes:
    from openpyxl.styles import Alignment, Border, Font, Side
    wb, ws = _xlsx_frame(data["title"], meta, stamp, 6)
    ws["A3"] = (f"Total teams: {data['total_teams']}    Mentor assigned: {data['assigned_teams']}    "
                f"Not assigned: {data['total_teams'] - data['assigned_teams']}")
    cols = ["Team ID", "Team Name", "Team Lead", "Mentor Name", "Mentor ID", "Mentor Email"]
    _header_row(ws, 5, cols, [10, 30, 28, 28, 16, 38])
    thin = Side(style="thin", color="CBD5E1")
    box = Border(top=thin, bottom=thin, left=thin, right=thin)
    for i, row in enumerate(data["rows"], 6):
        vals = [row["team_id"], _safe(row["team_name"]), _safe(row["lead_name"]), _safe(row["mentor_name"]),
                _safe(row["mentor_id"]), _safe(row["mentor_email"])]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(row=i, column=c, value=v)
            cell.border = box
            cell.alignment = Alignment(horizontal="center" if c == 1 else "left", vertical="center")
            if c == 4 and not row["assigned"]:
                cell.font = Font(italic=True, color="B45309")
    ws.freeze_panes = "A6"
    ws.auto_filter.ref = f"A5:F{5 + max(len(data['rows']), 1)}"
    return _xlsx_bytes(wb)
