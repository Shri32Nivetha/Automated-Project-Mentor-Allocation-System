import React, { useCallback, useEffect, useState } from "react";
import { api, download, fmt, fmtDate } from "../api.js";
import { Badge, Card, DataTable, Empty, Field, Modal, MultiSelect, PageHead, Spinner, Stat, resetDomainCache, useAsync, useConfirm, useDomains, useToast } from "../ui.jsx";
import { CycleSelect, NoCycle } from "./common.jsx";
export { AdminDashboard } from "./admin_dashboard.jsx";
export { AdminFaculty, AdminWorkload } from "./admin_faculty.jsx";
export { AdminAllocation } from "./admin_allocation.jsx";
export { AdminTeamComposition, AdminTeamMentor } from "./admin_team_reports.jsx";

const PSTATUS = ["submitted", "under_review", "approved", "needs_revision", "rejected", "allocated", "finalised"];

/* ------------------------------------------------------------ teams */
function TeamModal({ id, onClose, onChange }) {
  const { data: t, loading, reload } = useAsync(() => api(`/admin/teams/${id}`), [id]);
  const toast = useToast(), confirm = useConfirm();
  const [m, setM] = useState(null);
  const [tm, setTm] = useState(null);
  if (loading || !t) return <Modal title="Team" onClose={onClose}><Spinner /></Modal>;
  const run = async (fn, msg) => { try { await fn(); toast.success(msg); setM(null); setTm(null); reload(); onChange(); } catch (x) { toast.error(x.message); } };
  const body = (v) => ({ full_name: v.full_name, email: v.email, registration_number: v.registration_number, department: v.department || undefined, programme: v.programme || undefined, year_semester: v.year_semester || undefined });
  return (
    <Modal title={t.name} onClose={onClose} wide>
      <div className="row" style={{ marginBottom: 10 }}><Badge value={t.proposal.status} />{t.allocation && <Badge value={`guide: ${t.allocation.faculty.name}`} tone="ok" />}<button className="btn sm" onClick={() => setTm({ name: t.name, department: t.department, programme: t.programme, year_semester: t.year_semester })}>Correct team details</button><button className="btn sm" onClick={() => setM({ new: true, full_name: "", email: "", registration_number: "", department: "", programme: "", year_semester: "" })}>Add member</button></div>
      <dl className="kv"><dt>Cycle</dt><dd>{t.cycle.name}</dd><dt>Department / programme</dt><dd>{t.department} / {t.programme}</dd><dt>Leader</dt><dd>{t.leader.name} ({t.leader.email})</dd><dt>Project</dt><dd>{t.proposal.title || "—"}</dd><dt>Primary domain</dt><dd>{t.domains.primary?.name || "—"}</dd></dl>
      {tm && <form className="card" onSubmit={(e) => { e.preventDefault(); run(() => api(`/admin/teams/${id}`, { method: "PATCH", body: tm }), "Team corrected (audited)"); }}><div className="form-grid">{["name", "department", "programme", "year_semester"].map((k) => <Field key={k} label={k.replace("_", " ")}><input value={tm[k]} onChange={(e) => setTm({ ...tm, [k]: e.target.value })} /></Field>)}</div><button className="btn primary">Save</button> <button type="button" className="btn" onClick={() => setTm(null)}>Cancel</button></form>}
      {m && <form className="card" onSubmit={(e) => { e.preventDefault(); run(() => (m.new ? api(`/admin/teams/${id}/members`, { method: "POST", body: body(m) }) : api(`/admin/teams/${id}/members/${m.id}`, { method: "PUT", body: body(m) })), "Saved (audited)"); }}><div className="form-grid">{[["full_name", "Name"], ["email", "E-mail"], ["registration_number", "Registration no."], ["department", "Department"], ["programme", "Programme"], ["year_semester", "Year / semester"]].map(([k, l]) => <Field key={k} label={l}><input value={m[k]} onChange={(e) => setM({ ...m, [k]: e.target.value })} /></Field>)}</div><button className="btn primary">Save</button> <button type="button" className="btn" onClick={() => setM(null)}>Cancel</button></form>}
      <div className="table-wrap" style={{ marginTop: 12 }}><table><thead><tr><th>Name</th><th>Reg. no.</th><th>E-mail</th><th>Dept / programme</th><th /></tr></thead><tbody>
        {t.members.map((x) => <tr key={x.id}><td>{x.full_name} {x.is_leader && <Badge value="leader" tone="ok" />}</td><td>{x.registration_number}</td><td>{x.email}</td><td>{x.department} / {x.programme}</td>
          <td><div className="row"><button className="btn sm" onClick={() => setM(x)}>Edit</button>{!x.is_leader && <button className="btn sm" onClick={async () => { if (await confirm({ title: "Remove member", message: `Remove ${x.full_name}?`, danger: true })) run(() => api(`/admin/teams/${id}/members/${x.id}`, { method: "DELETE" }), "Member removed (audited)"); }}>Remove</button>}</div></td></tr>)}
      </tbody></table></div>
    </Modal>
  );
}

export function AdminTeams() {
  const [sel, setSel] = useState(null);
  const [k, setK] = useState(0);
  const [cid, setCid] = useState(null);
  const load = useCallback((p) => api("/admin/teams", { params: { ...p, cycle_id: cid } }), [cid]);
  const { data: crs, reload } = useAsync(() => api("/admin/change-requests"), [k]);
  const toast = useToast(), confirm = useConfirm();
  const resolve = async (c, action) => { const r = await confirm({ title: `${action === "approve" ? "Approve" : "Reject"} request`, message: c.description, reasonRequired: true, reasonLabel: "Remarks", confirmLabel: action === "approve" ? "Approve" : "Reject" }); if (!r) return; try { await api(`/admin/change-requests/${c.id}/resolve`, { method: "POST", body: { action, remarks: r.reason } }); toast.success("Resolved"); setK(k + 1); reload(); } catch (x) { toast.error(x.message); } };
  return (
    <>
      <PageHead title="Team registrations" actions={<CycleSelect value={cid} onChange={setCid} />} />
      {crs?.items.length > 0 && <Card title={`Pending membership change requests (${crs.total})`}>{crs.items.map((c) => <div className="notif" key={c.id}><div><b>{c.team_name}</b><div className="small">{c.description}</div></div><div className="row"><button className="btn sm teal" onClick={() => resolve(c, "approve")}>Approve</button><button className="btn sm" onClick={() => resolve(c, "reject")}>Reject</button></div></div>)}</Card>}
      <Card>
        <DataTable load={load} refreshKey={k + String(cid)} onRow={(r) => setSel(r.id)} searchPlaceholder="Search team, leader, member, reg. no., project…"
          filters={[{ key: "proposal_status", label: "Proposal", options: ["draft", ...PSTATUS] }, { key: "allocated", label: "Guide", options: [{ value: "true", label: "allocated" }, { value: "false", label: "not allocated" }] }]}
          columns={[
            { key: "name", label: "Team", sort: "name", render: (r) => <div><b>{r.name}</b><div className="small muted">{r.leader} · {r.members} members</div></div> },
            { key: "department", label: "Department", sort: "department" }, { key: "project_title", label: "Project", sort: "title", render: (r) => r.project_title || "—" },
            { key: "primary_domain", label: "Domain" }, { key: "proposal_status", label: "Proposal", sort: "status", render: (r) => <Badge value={r.proposal_status} /> },
            { key: "guide", label: "Guide", render: (r) => r.guide || "—" },
          ]} />
      </Card>
      {sel && <TeamModal id={sel} onClose={() => setSel(null)} onChange={() => setK(k + 1)} />}
    </>
  );
}

/* ------------------------------------------------------------ proposals */
function ProposalModal({ id, onClose, onChange }) {
  const { data, loading, reload } = useAsync(() => api(`/admin/proposals/${id}`), [id]);
  const toast = useToast(), confirm = useConfirm();
  if (loading || !data) return <Modal title="Proposal" onClose={onClose}><Spinner /></Modal>;
  const t = data.team, p = t.proposal;
  const review = async (action, needRemarks, title) => {
    let remarks = "";
    if (needRemarks) { const r = await confirm({ title, message: `Team: ${t.name}`, reasonRequired: true, reasonLabel: "Remarks (visible to the team leader)", danger: action === "reject", confirmLabel: title }); if (!r) return; remarks = r.reason; }
    else if (action === "approve" && !(await confirm({ title: "Approve proposal", message: "Approving also marks the team eligible for guide allocation." }))) return;
    try { await api(`/admin/proposals/${id}/review`, { method: "POST", body: { action, remarks } }); toast.success("Proposal updated"); reload(); onChange(); } catch (x) { toast.error(x.message); }
  };
  const locked = !!t.allocation;
  return (
    <Modal title={p.title || t.name} onClose={onClose} wide>
      <div className="row" style={{ marginBottom: 12 }}>
        <Badge value={p.status} /> {p.eligible_for_allocation && <Badge value="eligible" tone="ok" />}
        {p.status === "submitted" && <button className="btn sm" onClick={() => review("start_review")}>Start review</button>}
        {["submitted", "under_review"].includes(p.status) && <button className="btn sm teal" onClick={() => review("approve")}>Approve</button>}
        {["submitted", "under_review", "approved"].includes(p.status) && !locked && <><button className="btn sm" onClick={() => review("request_revision", true, "Request revision")}>Request revision</button><button className="btn sm danger" onClick={() => review("reject", true, "Reject")}>Reject</button></>}
        {p.status === "approved" && <button className="btn sm" onClick={async () => { try { await api(`/admin/proposals/${id}/review`, { method: "POST", body: { action: "set_eligibility", eligible: !p.eligible_for_allocation } }); reload(); onChange(); } catch (x) { toast.error(x.message); } }}>{p.eligible_for_allocation ? "Mark ineligible" : "Mark eligible"}</button>}
      </div>
      {locked && <div className="alert info">This team already has a guide; unassign it (Guide allocation) before changing the review.</div>}
      <dl className="kv"><dt>Team</dt><dd>{t.name} ({t.members.length} members)</dd><dt>Primary domain</dt><dd>{p.primary_domain?.name || "—"} {p.primary_domain?.is_custom && <Badge value="custom" />}</dd><dt>Interests</dt><dd>{p.interest_domains.map((d) => d.name).join(", ") || "—"}</dd><dt>Technologies</dt><dd>{p.technologies.join(", ") || "—"}</dd><dt>Submitted</dt><dd>{fmt(p.submitted_at)}</dd></dl>
      <h3 style={{ marginTop: 12 }}>Description</h3><p style={{ whiteSpace: "pre-line" }}>{p.description}</p>
      {p.objectives && <><h3>Objectives</h3><p style={{ whiteSpace: "pre-line" }}>{p.objectives}</p></>}
      {p.expected_outcomes && <><h3>Expected outcomes</h3><p style={{ whiteSpace: "pre-line" }}>{p.expected_outcomes}</p></>}
      <h3>Review history</h3>
      <div className="timeline">{[...p.reviews].reverse().map((r) => <div key={r.id}><b>{r.from_status} → {r.to_status}</b> <span className="small muted">{fmt(r.created_at)}</span><div>{r.remarks}</div></div>)}</div>
    </Modal>
  );
}
export function AdminProposals() {
  const [sel, setSel] = useState(null);
  const [k, setK] = useState(0);
  const load = useCallback((p) => api("/admin/proposals", { params: p }), []);
  return (
    <>
      <PageHead title="Project proposal review" sub="Only approved + eligible proposals enter allocation." />
      <Card><DataTable load={load} refreshKey={k} onRow={(r) => setSel(r.id)} filters={[{ key: "status", label: "Status", options: PSTATUS }]} searchPlaceholder="Search title or team"
        columns={[{ key: "title", label: "Title", sort: "title" }, { key: "team_name", label: "Team", sort: "team" }, { key: "primary_domain", label: "Domain" },
          { key: "status", label: "Status", sort: "status", render: (r) => <Badge value={r.status} /> }, { key: "eligible", label: "Eligible", render: (r) => (r.eligible ? "Yes" : "No") }, { key: "submitted_at", label: "Submitted", sort: "submitted", render: (r) => fmtDate(r.submitted_at) }]} /></Card>
      {sel && <ProposalModal id={sel} onClose={() => setSel(null)} onChange={() => setK(k + 1)} />}
    </>
  );
}

/* ------------------------------------------------------------ domains */
export function AdminDomains() {
  const [k, setK] = useState(0);
  const toast = useToast(), confirm = useConfirm();
  const domains = useDomains();
  const [form, setForm] = useState(null);
  const load = useCallback((p) => api("/admin/domains", { params: { ...p, page_size: 100 } }), []);
  const run = async (fn, msg) => { try { await fn(); resetDomainCache(); toast.success(msg); setForm(null); setK(k + 1); } catch (x) { toast.error(x.message); } };
  const mapIt = async (d) => { const r = await confirm({ title: "Map custom domain", message: `Type the exact name of an existing domain to use as the parent of “${d.name}” (matching will then follow that domain).`, reasonRequired: true, reasonLabel: "Existing domain name" }); if (!r) return; const t = domains.find((x) => x.name.toLowerCase() === r.reason.toLowerCase()); if (!t) return toast.error("No active domain with that name."); run(() => api(`/admin/domains/${d.id}/review-custom`, { method: "POST", body: { action: "map", map_to_domain_id: t.id } }), "Mapped"); };
  return (
    <>
      <PageHead title="Domain catalogue" sub="Stored in MySQL and used by teams, faculty and matching." actions={<button className="btn primary" onClick={() => setForm({ name: "", description: "", parent_id: "" })}>New domain</button>} />
      {form && <Card title={form.id ? "Edit domain" : "New domain"}><form onSubmit={(e) => { e.preventDefault(); const b = { name: form.name, description: form.description }; if (form.id) run(() => api(`/admin/domains/${form.id}`, { method: "PATCH", body: { ...b, parent_id: form.parent_id ? Number(form.parent_id) : null, clear_parent: !form.parent_id } }), "Domain updated"); else run(() => api("/admin/domains", { method: "POST", body: { ...b, parent_id: form.parent_id ? Number(form.parent_id) : null } }), "Domain created"); }}>
        <div className="form-grid"><Field label="Name" required><input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Parent domain" hint="Used for related-domain matching"><select value={form.parent_id ?? ""} onChange={(e) => setForm({ ...form, parent_id: e.target.value })}><option value="">None</option>{domains.filter((d) => d.id !== form.id).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></Field>
          <Field label="Description"><input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field></div>
        <button className="btn primary">Save</button> <button type="button" className="btn" onClick={() => setForm(null)}>Cancel</button></form></Card>}
      <Card><DataTable load={load} refreshKey={k} pageSize={100} searchPlaceholder="Search domains"
        filters={[{ key: "custom_status", label: "Custom review", options: ["pending", "approved", "rejected"] }, { key: "active", label: "Active", options: [{ value: "true", label: "active" }, { value: "false", label: "inactive" }] }]}
        columns={[{ key: "name", label: "Domain", render: (d) => <div><b>{d.name}</b> {d.is_custom && <Badge value={`custom ${d.custom_status}`} tone="warn" />}<div className="small muted">{d.description}</div></div> },
          { key: "usage", label: "Used by", render: (d) => `${d.team_usage} teams · ${d.faculty_usage} faculty` }, { key: "is_active", label: "Status", render: (d) => <Badge value={d.is_active ? "active" : "inactive"} tone={d.is_active ? "ok" : "muted"} /> },
          { key: "a", label: "", render: (d) => <div className="row">
            {d.is_custom && d.custom_status === "pending" && <><button className="btn sm teal" onClick={() => run(() => api(`/admin/domains/${d.id}/review-custom`, { method: "POST", body: { action: "approve" } }), "Approved")}>Approve</button><button className="btn sm" onClick={() => mapIt(d)}>Map…</button><button className="btn sm" onClick={() => run(() => api(`/admin/domains/${d.id}/review-custom`, { method: "POST", body: { action: "reject" } }), "Rejected")}>Reject</button></>}
            {!d.is_other && <button className="btn sm" onClick={() => setForm({ ...d, parent_id: d.parent_id ?? "" })}>Edit</button>}
            {!d.is_other && <button className="btn sm" onClick={() => run(() => api(`/admin/domains/${d.id}`, { method: "PATCH", body: { is_active: !d.is_active } }), d.is_active ? "Deactivated (references kept)" : "Activated")}>{d.is_active ? "Deactivate" : "Activate"}</button>}</div> }]} /></Card>
    </>
  );
}

/* ------------------------------------------------------------ cycles */
export function AdminCycles() {
  const { data, loading, reload } = useAsync(() => api("/admin/cycles"), []);
  const toast = useToast(), confirm = useConfirm();
  const [f, setF] = useState(null);
  const run = async (fn, msg) => { try { await fn(); toast.success(msg); setF(null); reload(); } catch (x) { toast.error(x.message); } };
  const iso = (v) => (v ? new Date(v).toISOString() : null);
  const activate = async (c) => { if (await confirm({ title: "Activate cycle", message: `Make “${c.name}” the current cycle? New registrations, dashboards and allocation runs will use it. Other cycles stay unchanged.` })) run(() => api(`/admin/cycles/${c.id}/activate`, { method: "POST" }), "Cycle activated"); };
  return (
    <>
      <PageHead title="Academic cycles" actions={<button className="btn primary" onClick={() => setF({ name: "", academic_year: "", registration_deadline: "", proposal_deadline: "" })}>New cycle</button>} />
      {f && <Card title="New cycle"><form onSubmit={(e) => { e.preventDefault(); run(() => api("/admin/cycles", { method: "POST", body: { name: f.name, academic_year: f.academic_year, registration_deadline: iso(f.registration_deadline), proposal_deadline: iso(f.proposal_deadline) } }), "Cycle created"); }}>
        <div className="form-grid"><Field label="Name" required><input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="e.g. 2026-27 Semester 7" /></Field><Field label="Academic year" required><input required value={f.academic_year} onChange={(e) => setF({ ...f, academic_year: e.target.value })} placeholder="2026-27" /></Field>
          <Field label="Registration deadline (optional)"><input type="datetime-local" value={f.registration_deadline} onChange={(e) => setF({ ...f, registration_deadline: e.target.value })} /></Field><Field label="Proposal submission deadline (optional)"><input type="datetime-local" value={f.proposal_deadline} onChange={(e) => setF({ ...f, proposal_deadline: e.target.value })} /></Field></div>
        <button className="btn primary">Create</button> <button type="button" className="btn" onClick={() => setF(null)}>Cancel</button></form></Card>}
      <Card>{loading ? <Spinner /> : !data.length ? <Empty>No cycles yet. Create one, then activate it so teams can register.</Empty> : <div className="table-wrap"><table><thead><tr><th>Cycle</th><th>Year</th><th>Status</th><th>Registration deadline</th><th>Proposal deadline</th><th>Finalised</th><th /></tr></thead><tbody>
        {data.map((c) => <tr key={c.id}><td><b>{c.name}</b> {c.is_active && <Badge value="current" tone="ok" />}</td><td>{c.academic_year}</td><td><Badge value={c.status} /></td><td>{fmt(c.registration_deadline)}</td><td>{fmt(c.proposal_deadline)}</td><td>{fmt(c.finalised_at)}</td>
          <td><div className="row">{!c.is_active && c.status !== "archived" && <button className="btn sm" onClick={() => activate(c)}>Activate</button>}{!c.is_active && c.status !== "archived" && <button className="btn sm" onClick={() => run(() => api(`/admin/cycles/${c.id}`, { method: "PATCH", body: { status: "archived" } }), "Archived")}>Archive</button>}</div></td></tr>)}</tbody></table></div>}</Card>
    </>
  );
}

/* ------------------------------------------------------------ reports / history / audit / settings */
const REPORTS = [["registrations", "Team registrations"], ["teams-by-domain", "Teams by domain"], ["proposal-status", "Proposal review status"], ["faculty-workload", "Faculty workload"], ["faculty-capacity", "Faculty capacity & remaining"], ["allocations", "Guide allocations"], ["unallocated", "Unallocated teams & reasons"], ["allocation-history", "Allocation history"]];
export function AdminReports() {
  const [cid, setCid] = useState(null);
  const [name, setName] = useState("registrations");
  const toast = useToast();
  const { data, loading, error } = useAsync(() => (cid ? api(`/admin/reports/${name}`, { params: { cycle_id: cid } }) : Promise.resolve(null)), [cid, name]);
  return (
    <>
      <PageHead title="Reports" sub="Live data from MySQL; export any report as CSV." actions={<><CycleSelect value={cid} onChange={setCid} /><button className="btn primary" disabled={!cid} onClick={() => download(`/admin/reports/${name}`, `${name}.csv`, { cycle_id: cid, format: "csv" }).catch((x) => toast.error(x.message))}>Download CSV</button></>} />
      <div className="tabs">{REPORTS.map(([k, l]) => <button key={k} className={name === k ? "on" : ""} onClick={() => setName(k)}>{l}</button>)}</div>
      {error && <div className="alert error">{error}</div>}
      <Card>{loading || !data ? <Spinner /> : !data.rows.length ? <Empty>No rows.</Empty> : <div className="table-wrap"><table className="report"><thead><tr>{data.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead><tbody>{data.rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j}>{/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(String(v)) ? fmt(String(v)) : String(v ?? "")}</td>)}</tr>)}</tbody></table></div>}</Card>
    </>
  );
}
export function AdminHistory() {
  const [cid, setCid] = useState(null);
  const load = useCallback((p) => api("/admin/allocation-history", { params: { ...p, cycle_id: cid } }), [cid]);
  return <><PageHead title="Allocation history" actions={<CycleSelect value={cid} onChange={setCid} />} /><Card><DataTable load={load} refreshKey={cid} filters={[{ key: "action", label: "Action", options: ["auto_assign", "manual_assign", "reassign", "unassign", "finalise"] }]} searchPlaceholder="(filter by action)"
    columns={[{ key: "created_at", label: "When", render: (r) => fmt(r.created_at) }, { key: "team", label: "Team" }, { key: "action", label: "Action", render: (r) => <Badge value={r.action} tone="muted" /> }, { key: "old_faculty", label: "From", render: (r) => r.old_faculty || "—" }, { key: "new_faculty", label: "To", render: (r) => r.new_faculty || "—" }, { key: "reason", label: "Reason" }, { key: "performed_by", label: "By" }]} /></Card></>;
}
export function AdminAudit() {
  const load = useCallback((p) => api("/admin/audit-logs", { params: { page: p.page, page_size: p.page_size, search: p.search, action: p.action } }), []);
  return <><PageHead title="Audit logs" sub="Every administrative change is recorded." /><Card><DataTable load={load} searchPlaceholder="Search by actor name or e-mail" pageSize={25}
    columns={[{ key: "created_at", label: "When", render: (r) => fmt(r.created_at) }, { key: "actor", label: "Actor", render: (r) => r.actor || "system" }, { key: "action", label: "Action" }, { key: "entity", label: "Entity", render: (r) => `${r.entity_type} ${r.entity_id ?? ""}` }, { key: "details", label: "Details", render: (r) => <code className="mono clamp" title={r.details ? JSON.stringify(r.details) : ""}>{r.details ? JSON.stringify(r.details) : ""}</code> }]} /></Card></>;
}
export function AdminSettings() {
  const { data, loading, reload } = useAsync(() => api("/admin/settings"), []);
  const toast = useToast();
  const [v, setV] = useState(null);
  useEffect(() => { if (data) setV({ ...data.values, designation_capacity_defaults: JSON.stringify(data.values.designation_capacity_defaults, null, 2) }); }, [data]);
  if (loading || !v) return <Spinner />;
  const d = data.descriptions;
  const save = async (e) => {
    e.preventDefault();
    let defs; try { defs = JSON.parse(v.designation_capacity_defaults); } catch { return toast.error("Designation defaults must be valid JSON, e.g. {\"HOD\": 5}."); }
    try { await api("/admin/settings", { method: "PUT", body: { values: { ...v, min_team_size: Number(v.min_team_size), max_team_size: Number(v.max_team_size), min_compatibility_score: Number(v.min_compatibility_score), default_faculty_capacity: Number(v.default_faculty_capacity), designation_capacity_defaults: defs } } }); toast.success("Settings saved"); reload(); } catch (x) { toast.error(x.message); }
  };
  const num = (k, l) => <Field label={l} hint={d[k]}><input type="number" min="0" value={v[k]} onChange={(e) => setV({ ...v, [k]: e.target.value })} /></Field>;
  const bool = (k, l) => <Field label={l} hint={d[k]}><select value={String(v[k])} onChange={(e) => setV({ ...v, [k]: e.target.value === "true" })}><option value="false">No</option><option value="true">Yes</option></select></Field>;
  return (
    <>
      <PageHead title="System settings" />
      <form onSubmit={save}>
        <Card title="Team rules"><div className="form-grid">{num("min_team_size", "Minimum team size")}{num("max_team_size", "Maximum team size")}{bool("allow_cross_department", "Allow cross-department teams")}{bool("allow_cross_programme", "Allow cross-programme teams")}<div className="full"><Field label="Allowed institutional e-mail domains" hint={d.allowed_email_domains}><input value={v.allowed_email_domains} onChange={(e) => setV({ ...v, allowed_email_domains: e.target.value })} placeholder="college.edu, students.college.edu" /></Field></div></div></Card>
        <Card title="Allocation rules"><div className="form-grid">{num("min_compatibility_score", "Minimum compatibility score")}{bool("restrict_faculty_to_team_department", "Restrict faculty to team department")}</div></Card>
        <Card title="Faculty capacity suggestions"><div className="form-grid">{num("default_faculty_capacity", "Default capacity suggestion")}</div><Field label="Designation defaults (JSON)" hint={d.designation_capacity_defaults}><textarea rows={7} value={v.designation_capacity_defaults} onChange={(e) => setV({ ...v, designation_capacity_defaults: e.target.value })} /></Field></Card>
        <button className="btn primary">Save settings</button>
      </form>
    </>
  );
}
