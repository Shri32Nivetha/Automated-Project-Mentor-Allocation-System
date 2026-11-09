import React, { useCallback, useState } from "react";
import { Check, Eye, Pencil, X as XIcon, UsersRound, Clock, UserCheck, CheckCircle2, Gauge, Target } from "lucide-react";
import { api, fmt } from "../api.js";
import { Alert, Badge, Btn, Card, DataTable, Empty, Field, Modal, MultiSelect, NumberInput, PageHead, Skeleton, Stat, TierBadge, UtilBar,
  useAsync, useConfirm, useDomains, useToast, validateWholeNumber } from "../ui.jsx";
import { CycleSelect } from "./common.jsx";

const DEFAULT_LIMITS = { min: 1, max: 100 };

/* ------------------------------------------------------------------ approval dialog (numeric capacity) */
export function ApproveDialog({ faculty, limits = DEFAULT_LIMITS, onClose, onDone }) {
  const toast = useToast();
  const [value, setValue] = useState("");            // deliberately empty: the administrator must choose a capacity
  const [bad, setBad] = useState(false);
  const [touched, setTouched] = useState(false);
  const [serverErr, setServerErr] = useState("");
  const [remarks, setRemarks] = useState("");
  const [busy, setBusy] = useState(false);
  const localErr = validateWholeNumber(value, { min: limits.min, max: limits.max, badInput: bad });
  const error = serverErr || (touched ? localErr : "");
  const set = (v, badInput) => { setValue(v); setBad(badInput); setServerErr(""); };

  const submit = async (e) => {
    e.preventDefault();
    setTouched(true);
    if (localErr) return;
    setBusy(true);
    try {
      const r = await api(`/admin/faculty/${faculty.id}/approve`, { method: "POST", body: { capacity: Number(value), remarks } });
      toast.success(`${faculty.full_name} approved with a capacity of ${r.capacity} project(s).`);
      onDone();
    } catch (x) {
      if (x.fieldErrors?.capacity) setServerErr(x.fieldErrors.capacity); else toast.error(x.message);
    } finally { setBusy(false); }
  };
  return (
    <Modal title={`Approve ${faculty.full_name}`} onClose={onClose} dismissible={!busy}
      footer={<><button type="button" className="btn" onClick={onClose} disabled={busy}>Cancel</button>
        <Btn type="submit" form="approve-form" className="primary" busy={busy}><Check size={15} aria-hidden /> Approve faculty</Btn></>}>
      <form id="approve-form" onSubmit={submit} noValidate>
        <p className="muted small" style={{ marginTop: 0 }}>{faculty.designation} · {faculty.department}. Approval lets this faculty member receive project teams.</p>
        <Field label="Project supervision capacity (maximum projects)" required error={error}
          hint={`Whole number from ${limits.min} to ${limits.max}. Counts team projects, not students. Requested by the faculty member: ${faculty.requested_capacity}.`}>
          <NumberInput value={value} onChange={set} min={limits.min} max={limits.max} placeholder={`e.g. ${faculty.suggested_capacity}`} data-autofocus onBlur={() => setTouched(true)} />
        </Field>
        <div className="quick" style={{ marginBottom: 14 }} aria-label="Quick fill">
          <button type="button" className="btn sm" onClick={() => set(String(faculty.requested_capacity), false)}>Use requested ({faculty.requested_capacity})</button>
          <button type="button" className="btn sm" onClick={() => set(String(faculty.suggested_capacity), false)}>Use suggested for {faculty.designation} ({faculty.suggested_capacity})</button>
        </div>
        <Field label="Remarks (optional)" hint="Shown to the faculty member in their notification."><textarea rows={2} value={remarks} maxLength={500} onChange={(e) => setRemarks(e.target.value)} /></Field>
      </form>
    </Modal>
  );
}

/* ------------------------------------------------------------------ capacity edit dialog */
export function CapacityDialog({ faculty, limits = DEFAULT_LIMITS, cycleId, onClose, onSaved }) {
  const toast = useToast();
  const [value, setValue] = useState(String(faculty.max_capacity ?? ""));
  const [bad, setBad] = useState(false);
  const [reason, setReason] = useState("");
  const [ack, setAck] = useState(false);
  const [touched, setTouched] = useState(false);
  const [serverErr, setServerErr] = useState("");
  const [busy, setBusy] = useState(false);
  const localErr = validateWholeNumber(value, { min: limits.min, max: limits.max, badInput: bad });
  const n = Number(value);
  const overload = !localErr && n < faculty.assigned ? faculty.assigned - n : 0;
  const reasonErr = touched && reason.trim().length < 3 ? "Enter a reason (at least 3 characters)." : "";
  const save = async (e) => {
    e.preventDefault();
    setTouched(true);
    if (localErr || reason.trim().length < 3 || (overload && !ack)) return;
    setBusy(true);
    try {
      await api(`/admin/faculty/${faculty.id}/capacity`, { method: "PUT", body: { max_capacity: n, reason: reason.trim(), cycle_id: cycleId || undefined,
        confirm_below_assigned: ack, expected_capacity: faculty.max_capacity } });
      toast.success(overload ? "Capacity updated; existing teams were kept." : "Capacity updated.");
      onSaved();
    } catch (x) {
      if (x.fieldErrors?.max_capacity) setServerErr(x.fieldErrors.max_capacity); else toast.error(x.message);
    } finally { setBusy(false); }
  };
  return (
    <Modal title={`Capacity: ${faculty.name || faculty.full_name}`} onClose={onClose} dismissible={!busy}
      footer={<><button type="button" className="btn" onClick={onClose} disabled={busy}>Cancel</button>
        <Btn type="submit" form="capacity-form" className={overload ? "warn" : "primary"} busy={busy} disabled={!!localErr || (overload > 0 && !ack)}>Save capacity</Btn></>}>
      <form id="capacity-form" onSubmit={save} noValidate>
        <dl className="kv" style={{ marginBottom: 12 }}><dt>Currently assigned</dt><dd><b>{faculty.assigned}</b> team(s)</dd><dt>Current capacity</dt><dd>{faculty.max_capacity}</dd></dl>
        <Field label="Maximum projects" required error={serverErr || (touched || value !== String(faculty.max_capacity) ? localErr : "")} hint={`Whole number from ${limits.min} to ${limits.max}.`}>
          <NumberInput value={value} onChange={(v, b) => { setValue(v); setBad(b); setServerErr(""); setAck(false); }} min={limits.min} max={limits.max} data-autofocus />
        </Field>
        {overload > 0 && (
          <Alert tone="warn" strong title="This creates an overload.">
            {faculty.name || faculty.full_name} already supervises {faculty.assigned} team(s); a capacity of {n} means <b>{overload} over capacity</b>.
            Existing teams are <b>not removed or reassigned</b>. The optimiser will avoid giving more teams where it can.
            <label className="check" style={{ marginTop: 6 }}><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> I understand and want to reduce the capacity anyway</label>
          </Alert>)}
        <Field label="Reason for the change" required error={reasonErr}><textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} /></Field>
      </form>
    </Modal>
  );
}

/* ------------------------------------------------------------------ faculty detail */
function FacultyModal({ id, limits, onClose, onChange }) {
  const { data: p, loading, reload } = useAsync(() => api(`/admin/faculty/${id}`), [id]);
  const domains = useDomains();
  const toast = useToast(), confirm = useConfirm();
  const [edit, setEdit] = useState(null);
  const [exp, setExp] = useState([]), [sup, setSup] = useState([]), [int, setInt] = useState([]), [custom, setCustom] = useState("");
  const [dialog, setDialog] = useState(null);
  const refresh = () => { reload(); onChange(); };
  const act = async (fn, msg) => { try { await fn(); toast.success(msg); refresh(); } catch (x) { toast.error(x.message); } };
  if (loading || !p) return <Modal title="Faculty" onClose={onClose} size="lg"><Skeleton lines={6} /></Modal>;
  const lim = p.capacity_limits || limits;
  const startEdit = () => {
    const ids = (l) => l.filter((d) => !d.is_custom).map((d) => d.id);
    setExp(ids(p.domains.expertise)); setSup(ids(p.domains.supported)); setInt(ids(p.domains.interest));
    setCustom(""); setEdit({ full_name: p.full_name, department: p.department, designation: p.designation, employee_id: p.employee_id, is_available: p.is_available });
  };
  const opts = domains.map((d) => ({ value: d.id, label: d.name }));
  const oth = domains.find((d) => d.is_other)?.id;
  const needsCustom = [exp, sup, int].some((l) => l.includes(oth));
  const reject = async () => { const r = await confirm({ title: "Reject registration", message: `Reject ${p.full_name}?`, danger: true, reasonRequired: true, reasonLabel: "Reason (shown to the faculty member)", confirmLabel: "Reject" }); if (r) act(() => api(`/admin/faculty/${id}/reject`, { method: "POST", body: { remarks: r.reason } }), "Registration rejected"); };
  const toggle = async () => { if (p.is_active && !(await confirm({ title: "Deactivate account", message: `${p.full_name} will be signed out and receive no new teams. Existing assignments are kept.`, danger: true, confirmLabel: "Deactivate" }))) return; act(() => api(`/admin/faculty/${id}/${p.is_active ? "deactivate" : "activate"}`, { method: "POST" }), p.is_active ? "Deactivated" : "Activated"); };
  const saveEdit = (e) => { e.preventDefault(); act(async () => { await api(`/admin/faculty/${id}`, { method: "PATCH", body: { ...edit, expertise_domain_ids: exp, supported_domain_ids: sup, interest_domain_ids: int, custom_domain_name: needsCustom ? custom : null } }); setEdit(null); }, "Profile updated"); };
  const w = p.workload;
  const cap = w ? { id: p.id, name: p.full_name, assigned: w.assigned, max_capacity: w.max_capacity } : null;
  return (
    <>
      <Modal title={p.full_name} onClose={onClose} size="lg">
        <div className="row" style={{ marginBottom: 14 }}>
          <Badge value={p.approval_status} /><Badge value={p.is_active ? "active" : "inactive"} /><Badge value={p.is_available ? "available" : "unavailable"} />
          <span style={{ flex: 1 }} />
          {p.approval_status !== "approved" && <button className="btn sm ok" onClick={() => setDialog("approve")}><Check size={14} aria-hidden /> Approve…</button>}
          {p.approval_status === "pending" && <button className="btn sm danger" onClick={reject}><XIcon size={14} aria-hidden /> Reject</button>}
          {p.approval_status === "approved" && cap && <button className="btn sm" onClick={() => setDialog("capacity")}>Edit capacity</button>}
          <button className="btn sm" onClick={startEdit}><Pencil size={13} aria-hidden /> Edit profile</button>
          <button className="btn sm" onClick={toggle}>{p.is_active ? "Deactivate" : "Activate"}</button>
        </div>
        {edit && (
          <form onSubmit={saveEdit} className="card flat">
            <div className="form-grid">
              {[["full_name", "Full name"], ["employee_id", "Employee ID"], ["department", "Department"], ["designation", "Designation"]].map(([k, l]) => <Field key={k} label={l}><input value={edit[k]} onChange={(e) => setEdit({ ...edit, [k]: e.target.value })} /></Field>)}
              <Field label="Availability"><select value={String(edit.is_available)} onChange={(e) => setEdit({ ...edit, is_available: e.target.value === "true" })}><option value="true">Available</option><option value="false">Not available</option></select></Field>
            </div>
            <MultiSelect label="Expertise" options={opts} value={exp} onChange={setExp} /><MultiSelect label="Supported domains" options={opts} value={sup} onChange={setSup} /><MultiSelect label="Interests" options={opts} value={int} onChange={setInt} />
            {needsCustom && <Field label="Custom domain name" required><input value={custom} onChange={(e) => setCustom(e.target.value)} /></Field>}
            <div className="row"><button className="btn primary">Save profile</button><button type="button" className="btn" onClick={() => setEdit(null)}>Cancel</button></div>
          </form>)}
        <div className="grid g2">
          <Card title="Profile"><dl className="kv"><dt>E-mail</dt><dd>{p.email}</dd><dt>Employee ID</dt><dd>{p.employee_id}</dd><dt>Department</dt><dd>{p.department}</dd><dt>Designation</dt><dd>{p.designation}</dd><dt>Requested capacity</dt><dd>{p.requested_capacity}</dd></dl></Card>
          <Card title="Workload & capacity">
            {w ? <>
              <dl className="kv"><dt>Cycle</dt><dd>{w.cycle.name}</dd><dt>Saved capacity</dt><dd><b>{w.max_capacity}</b> projects</dd><dt>Assigned now</dt><dd><b>{w.assigned}</b></dd></dl>
              <div style={{ marginTop: 10 }}><UtilBar assigned={w.assigned} capacity={w.max_capacity} /></div>
              {w.over_capacity && <div style={{ marginTop: 10 }}><Alert tone="warn" title="Overloaded.">Assigned projects exceed capacity by {w.assigned - w.max_capacity}.</Alert></div>}
            </> : <Empty>No active cycle.</Empty>}
          </Card>
        </div>
        <Card title="Domains"><p><b>Expertise:</b> {p.domains.expertise.map((d) => d.name).join(", ") || "—"}</p><p><b>Supported:</b> {p.domains.supported.map((d) => d.name).join(", ") || "—"}</p><p style={{ marginBottom: 0 }}><b>Interests:</b> {p.domains.interest.map((d) => d.name).join(", ") || "—"}</p></Card>
        <div className="grid g2">
          <Card title="Assignments">{p.assignments.length ? p.assignments.map((a) => <div className="notif" key={a.team_id}><span>{a.team_name}</span><span className="row"><TierBadge tier={a.is_override ? "override" : a.match_tier} /><Badge value={a.status} /></span></div>) : <Empty>No teams assigned.</Empty>}</Card>
          <Card title="Capacity history">{p.capacity_history.length ? p.capacity_history.map((c, i) => <div className="notif" key={i}><div>{c.old} → <b>{c.new}</b> <span className="small muted">({c.assigned} assigned)</span><div className="small muted">{c.reason}</div></div><span className="small muted">{fmt(c.created_at)}</span></div>) : <Empty>No changes yet.</Empty>}</Card>
        </div>
      </Modal>
      {dialog === "approve" && <ApproveDialog faculty={p} limits={lim} onClose={() => setDialog(null)} onDone={() => { setDialog(null); refresh(); }} />}
      {dialog === "capacity" && cap && <CapacityDialog faculty={cap} limits={lim} onClose={() => setDialog(null)} onSaved={() => { setDialog(null); refresh(); }} />}
    </>
  );
}

/* ------------------------------------------------------------------ faculty list */
export function AdminFaculty() {
  const [sel, setSel] = useState(null);
  const [approving, setApproving] = useState(null);
  const [k, setK] = useState(0);
  const toast = useToast(), confirm = useConfirm();
  const { data: meta } = useAsync(() => api("/admin/faculty-meta"), []);
  const limits = meta?.capacity_limits || DEFAULT_LIMITS;
  const load = useCallback((p) => api("/admin/faculty", { params: p }), []);
  const reject = async (r) => {
    const x = await confirm({ title: "Reject registration", message: `Reject ${r.full_name}?`, danger: true, reasonRequired: true, reasonLabel: "Reason (shown to the faculty member)", confirmLabel: "Reject" });
    if (!x) return;
    try { await api(`/admin/faculty/${r.id}/reject`, { method: "POST", body: { remarks: x.reason } }); toast.success("Registration rejected"); setK(k + 1); } catch (e) { toast.error(e.message); }
  };
  const stop = (fn) => (e) => { e.stopPropagation(); fn(); };
  return (
    <>
      <PageHead title="Faculty management" sub="Approve registrations, set project capacity and review each mentor's workload." />
      <Card>
        <DataTable load={load} refreshKey={k} onRow={(r) => setSel(r.id)} searchPlaceholder="Search name, e-mail or employee ID" pageSize={12}
          rowClass={(r) => (r.over_capacity ? "row-bad" : r.approval_status === "pending" ? "row-warn" : "")}
          filters={[{ key: "status", label: "Approval", options: ["pending", "approved", "rejected"] },
            { key: "department", label: "Department", options: meta?.departments || [] },
            { key: "available", label: "Availability", options: [{ value: "true", label: "Available" }, { value: "false", label: "Not available" }] },
            { key: "workload", label: "Workload", options: [{ value: "over", label: "Over capacity" }, { value: "full", label: "At capacity" }, { value: "free", label: "Has room" }] }]}
          columns={[
            { key: "full_name", label: "Faculty", sort: "name", render: (r) => <div className="cell-title"><b>{r.full_name}</b><span>{r.email}</span></div> },
            { key: "department", label: "Department", sort: "department", render: (r) => <div className="cell-title"><b>{r.department}</b><span>{r.designation}</span></div> },
            { key: "approval_status", label: "Approval", sort: "status", render: (r) => <Badge value={r.approval_status} /> },
            { key: "avail", label: "Availability", render: (r) => <div className="row" style={{ gap: 4 }}><Badge value={r.is_active ? "active" : "inactive"} /><Badge value={r.is_available ? "available" : "unavailable"} /></div> },
            { key: "cap", label: "Capacity", sort: "capacity", render: (r) => (r.approval_status === "approved" ? <b>{r.max_capacity}</b> : <span className="muted small">requested {r.requested_capacity}</span>) },
            { key: "assigned", label: "Assigned", sort: "assigned", render: (r) => (r.approval_status === "approved" ? r.assigned ?? 0 : "—") },
            { key: "util", label: "Utilisation", sort: "workload", render: (r) => (r.approval_status === "approved" && r.max_capacity !== undefined ? <UtilBar assigned={r.assigned} capacity={r.max_capacity} /> : "—") },
            { key: "actions", label: "", render: (r) => (
              <div className="row" style={{ gap: 4 }}>
                <button className="btn sm" onClick={stop(() => setSel(r.id))} aria-label={`View ${r.full_name}`}><Eye size={13} aria-hidden /> View</button>
                {r.approval_status !== "approved" && <button className="btn sm ok" onClick={stop(() => setApproving(r))} aria-label={`Approve ${r.full_name}`}>Approve</button>}
                {r.approval_status === "pending" && <button className="btn sm danger" onClick={stop(() => reject(r))} aria-label={`Reject ${r.full_name}`}>Reject</button>}
              </div>) },
          ]} />
      </Card>
      {sel && <FacultyModal id={sel} limits={limits} onClose={() => setSel(null)} onChange={() => setK((x) => x + 1)} />}
      {approving && <ApproveDialog faculty={approving} limits={limits} onClose={() => setApproving(null)} onDone={() => { setApproving(null); setK((x) => x + 1); }} />}
    </>
  );
}

/* ------------------------------------------------------------------ workload */
export function AdminWorkload() {
  const [cid, setCid] = useState(null);
  const [editing, setEditing] = useState(null);
  const { data: w, loading, error, reload } = useAsync(() => (cid ? api("/admin/workload", { params: { cycle_id: cid } }) : Promise.resolve(null)), [cid]);
  return (
    <>
      <PageHead title="Workload management" sub="Capacity is measured in team projects per cycle. Capacity is a nominal limit: when demand exceeds it, overload is spread as evenly as possible." actions={<CycleSelect value={cid} onChange={setCid} />} />
      {error && <Alert tone="error">{error}</Alert>}
      {loading || !w ? <Skeleton cards={6} lines={4} /> : (
        <>
          {w.capacity_shortage > 0 && <Alert tone="warn" strong title={`Capacity shortage of ${w.capacity_shortage} project(s).`}>{w.teams_requiring_guides} eligible team(s) need guides but only {w.available_capacity} capacity remains. Every team can still be allocated; the unavoidable overload will be spread across compatible mentors and shown in the preview. Increase capacity or approve more faculty to avoid it.</Alert>}
          {w.overloaded_faculty > 0 && <Alert tone="error" title={`${w.overloaded_faculty} faculty member(s) are above capacity (+${w.total_overload}).`}>Existing teams are never removed automatically.</Alert>}
          {w.capacity_shortage === 0 && w.capacity_surplus > 0 && <Alert tone="ok">Capacity surplus of {w.capacity_surplus} project(s).</Alert>}
          <div className="stats">
            <Stat label="Eligible teams" icon={UsersRound} value={w.eligible_teams_total} /><Stat label="Teams requiring guides" icon={Clock} value={w.teams_requiring_guides} tone="warn" />
            <Stat label="Eligible faculty" icon={UserCheck} value={w.eligible_faculty} sub="approved, active, available" /><Stat label="Existing allocations" icon={CheckCircle2} value={w.existing_allocations} />
            <Stat label="Total capacity" icon={Gauge} value={w.total_capacity} /><Stat label="Available capacity" icon={Target} value={w.available_capacity} tone="ok" />
            <Stat label="Shortage / surplus" value={w.capacity_shortage ? `−${w.capacity_shortage}` : `+${w.capacity_surplus}`} tone={w.capacity_shortage ? "bad" : "ok"} />
            <Stat label="Baseline per faculty" value={w.estimated_baseline ?? "—"} sub="teams ÷ eligible faculty" />
          </div>
          <Alert tone="info">{w.explanation}</Alert>
          <Card title="Faculty workload">
            <div className="table-wrap"><table className="stack"><thead><tr><th>Faculty</th><th>Department</th><th>Capacity</th><th>Utilisation</th><th>Eligible for new teams</th><th /></tr></thead><tbody>
              {w.faculty.filter((f) => f.approval_status === "approved").map((f) => (
                <tr key={f.id} className={f.over_capacity ? "row-bad" : ""}>
                  <td data-label="Faculty"><div className="cell-title"><b>{f.name}</b><span>{f.designation}</span></div></td>
                  <td data-label="Department">{f.department}</td><td data-label="Capacity"><b>{f.max_capacity}</b></td>
                  <td data-label="Utilisation"><UtilBar assigned={f.assigned} capacity={f.max_capacity} /></td>
                  <td data-label="Eligible">{f.eligible_for_allocation ? <Badge value="yes" tone="ok" /> : <span className="small muted">{f.ineligible_reason}</span>}</td>
                  <td data-label=""><button className="btn sm" onClick={() => setEditing(f)} aria-label={`Edit capacity of ${f.name}`}>Edit capacity</button></td>
                </tr>))}</tbody></table></div>
          </Card>
          {editing && <CapacityDialog faculty={editing} limits={w.capacity_limits} cycleId={cid} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload(); }} />}
        </>)}
    </>
  );
}
