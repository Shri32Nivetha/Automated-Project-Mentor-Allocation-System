import React, { useCallback, useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, Cpu, Search, ShieldAlert, Clock, UserCheck, Gauge } from "lucide-react";
import { api } from "../api.js";
import { Alert, Badge, Btn, Card, DataTable, Empty, Field, Modal, PageHead, Skeleton, Stat, TierBadge, UtilBar, useAsync, useConfirm, useToast } from "../ui.jsx";
import { CycleSelect, NoCycle } from "./common.jsx";

const TABS = [["auto", "Preview & allocate"], ["manual", "Manual / reassign"], ["current", "Current allocations"], ["un", "Requires resolution"], ["fin", "Finalise"]];

export function AdminAllocation() {
  const [cid, setCid] = useState(null);
  const [tab, setTab] = useState("auto");
  const [focusTeam, setFocusTeam] = useState(null);
  const { data: w } = useAsync(() => (cid ? api("/admin/workload", { params: { cycle_id: cid } }) : Promise.resolve(null)), [cid, tab]);
  const resolve = (t) => { setFocusTeam(t); setTab("manual"); };
  return (
    <>
      <PageHead title="Guide allocation" sub="Review the optimiser's proposal for the whole cycle, then commit it. Nothing changes until you confirm." actions={<CycleSelect value={cid} onChange={setCid} />} />
      {w && (
        <div className="stats">
          <Stat label="Teams awaiting a guide" icon={Clock} value={w.teams_requiring_guides} tone={w.teams_requiring_guides ? "warn" : "ok"} />
          <Stat label="Eligible faculty" icon={UserCheck} value={w.eligible_faculty} />
          <Stat label="Available capacity" icon={Gauge} value={w.available_capacity} sub={`of ${w.total_capacity}`} tone={w.capacity_shortage ? "warn" : ""} />
          <Stat label="Faculty over capacity" icon={AlertTriangle} value={w.overloaded_faculty} tone={w.overloaded_faculty ? "bad" : "ok"} />
        </div>)}
      <div className="tabs" role="tablist" aria-label="Allocation sections">
        {TABS.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      {!cid ? <NoCycle /> : tab === "auto" ? <AutoTab cid={cid} onResolve={resolve} /> : tab === "manual" ? <ManualTab cid={cid} focusTeam={focusTeam} /> :
        tab === "current" ? <CurrentTab cid={cid} /> : tab === "un" ? <UnTab cid={cid} onResolve={resolve} /> : <FinaliseTab cid={cid} />}
    </>
  );
}

/* ------------------------------------------------------------------ preview */
export function PolicyExplainer({ policy }) {
  return (
    <details className="card flat" style={{ padding: ".7rem 1rem" }}>
      <summary style={{ cursor: "pointer", fontWeight: 600 }}>How the allocation is decided</summary>
      <p className="small muted">The optimiser looks at every team and every eligible mentor together (not one team at a time), in this strict priority order:</p>
      <ol className="small">{(policy || []).map((p) => <li key={p}>{p.replace(/^\d\.\s*/, "")}</li>)}</ol>
    </details>
  );
}

function AutoTab({ cid, onResolve }) {
  const [pv, setPv] = useState(null);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const [reopt, setReopt] = useState(false);
  const [incMan, setIncMan] = useState(false);
  const [commitOpen, setCommitOpen] = useState(false);
  const [err, setErr] = useState("");
  const toast = useToast();
  const make = async () => {
    setBusy(true); setRes(null); setErr("");
    try { setPv(await api("/admin/allocation/preview", { method: "POST", body: { cycle_id: cid, reoptimize: reopt, include_manual: reopt && incMan } })); }
    catch (x) { setPv(null); setErr(x.message); } finally { setBusy(false); }
  };
  return (
    <>
      <Card>
        <div className="row between">
          <div>
            <b>Generate a proposal</b>
            <div className="muted small">Existing assignments are kept unless you choose to re-optimise. Manual assignments are always protected unless you explicitly include them.</div>
          </div>
          <Btn className="primary" busy={busy} onClick={make}><Cpu size={15} aria-hidden /> {busy ? "Optimising…" : "Generate allocation preview"}</Btn>
        </div>
        <div style={{ marginTop: 10 }}>
          <label className="check"><input type="checkbox" checked={reopt} onChange={(e) => { setReopt(e.target.checked); if (!e.target.checked) setIncMan(false); }} /> Also re-optimise existing <b>automatic</b> assignments that are not finalised</label>
          <label className="check" style={{ opacity: reopt ? 1 : .5 }}><input type="checkbox" disabled={!reopt} checked={incMan} onChange={(e) => setIncMan(e.target.checked)} /> Also include <b>manual</b> assignments (administrator decisions may be replaced)</label>
        </div>
      </Card>
      {err && <Alert tone="error" title="The proposal could not be created.">{err}</Alert>}
      {res && (
        <Alert tone={res.requires_resolution || res.overloaded?.length ? "warn" : "ok"} strong title="Allocation committed.">
          {res.message}
          {res.skipped?.length > 0 && <div>Skipped at commit (state changed since the preview): {res.skipped.map((s) => `team ${s.team_id} (${s.reason})`).join("; ")}.</div>}
          {res.requires_resolution > 0 && <div><b>Not every team has a compatible mentor</b>; open “Requires resolution” to assign them manually.</div>}
        </Alert>)}
      {pv && <PreviewResults pv={pv} onCommit={() => setCommitOpen(true)} onResolve={onResolve} />}
      {commitOpen && pv && <CommitDialog pv={pv} onClose={() => setCommitOpen(false)}
        onDone={(r) => { setRes(r); setPv(null); setCommitOpen(false); toast.success(r.message); }} />}
    </>
  );
}

const SORTS = { team: "Team name", mentor: "Mentor", tier: "Match tier", load: "Projected utilisation", score: "Compatibility score" };
export function PreviewResults({ pv, onCommit, onResolve }) {
  const [q, setQ] = useState("");
  const [tier, setTier] = useState("");
  const [mentor, setMentor] = useState("");
  const [onlyOver, setOnlyOver] = useState(false);
  const [sort, setSort] = useState("team");
  const s = pv.summary;
  const mentors = useMemo(() => [...new Map(pv.assignments.map((a) => [a.faculty_id, a.faculty_name])).entries()].sort((a, b) => a[1].localeCompare(b[1])), [pv]);
  const rows = useMemo(() => {
    const t = q.trim().toLowerCase();
    const f = pv.assignments.filter((a) => (!t || `${a.team_name} ${a.team_id} ${a.project_title} ${a.faculty_name} ${a.team_domain} ${a.team_interests.join(" ")}`.toLowerCase().includes(t))
      && (!tier || a.tier === tier) && (!mentor || String(a.faculty_id) === mentor) && (!onlyOver || a.overload > 0));
    const key = { team: (a) => a.team_name.toLowerCase(), mentor: (a) => a.faculty_name.toLowerCase(), tier: (a) => a.tier_rank, load: (a) => -(a.faculty_projected / Math.max(1, a.faculty_capacity)), score: (a) => -a.score }[sort];
    return [...f].sort((a, b) => (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : a.team_id - b.team_id));
  }, [pv, q, tier, mentor, onlyOver, sort]);
  const proj = [...pv.faculty_projection].filter((p) => p.added > 0 || p.overload > 0).sort((a, b) => (b.projected / Math.max(1, b.capacity)) - (a.projected / Math.max(1, a.capacity)));
  return (
    <>
      <div className="stats">
        <Stat label="Teams to assign" value={s.teams_assigned} tone="ok" sub={`${s.tier_counts.primary} primary · ${s.tier_counts.additional} additional · ${s.tier_counts.related} related`} />
        <Stat label="Require resolution" value={pv.unassigned.length} tone={pv.unassigned.length ? "bad" : "ok"} sub="no compatible mentor" />
        <Stat label="Total overload" value={s.total_overload} tone={s.total_overload ? "warn" : "ok"} sub={`worst +${s.max_overload} · ${s.overloaded_faculty} mentor(s)`} />
        <Stat label="Capacity shortage" value={s.capacity_shortage} tone={s.capacity_shortage ? "warn" : "ok"} />
      </div>
      {s.new_overload > 0 && <Alert tone="warn" strong title="This plan exceeds some mentors' nominal capacity.">Demand is higher than the capacity of compatible mentors, so the overload below is unavoidable and has been spread to keep the worst case as small as possible. You will be asked to acknowledge it.</Alert>}
      {pv.unassigned.length > 0 && <Alert tone="error" title={`${pv.unassigned.length} team(s) require administrative resolution.`}>No compatible, eligible mentor exists. They will <b>not</b> be assigned automatically; assign them manually with an override reason after committing.</Alert>}
      {!pv.solver.proved_optimal && <Alert tone="info">The optimiser reached its time limit, so this plan is valid but may not be the very best one. Generate the preview again for another attempt.</Alert>}
      <PolicyExplainer policy={pv.policy} />

      <Card title={`Proposed assignments (${rows.length}${rows.length !== pv.assignments.length ? ` of ${pv.assignments.length}` : ""})`}
        actions={<Btn className="ok" disabled={!pv.assignments.length} onClick={onCommit}>Review & commit…</Btn>}>
        <div className="toolbar" role="search">
          <div className="search"><Search size={16} aria-hidden /><input type="search" placeholder="Search team, project, domain or mentor" aria-label="Search proposed assignments" value={q} onChange={(e) => setQ(e.target.value)} /></div>
          <select aria-label="Filter by match tier" value={tier} onChange={(e) => setTier(e.target.value)}><option value="">Match: all</option><option value="primary">Primary</option><option value="additional">Additional</option><option value="related">Related</option></select>
          <select aria-label="Filter by mentor" value={mentor} onChange={(e) => setMentor(e.target.value)}><option value="">Mentor: all</option>{mentors.map(([id, n]) => <option key={id} value={id}>{n}</option>)}</select>
          <select aria-label="Sort by" value={sort} onChange={(e) => setSort(e.target.value)}>{Object.entries(SORTS).map(([k, l]) => <option key={k} value={k}>Sort: {l}</option>)}</select>
          <label className="check"><input type="checkbox" checked={onlyOver} onChange={(e) => setOnlyOver(e.target.checked)} /> Overload only</label>
        </div>
        {rows.length ? (
          <div className="table-wrap"><table className="stack"><thead><tr><th>Team</th><th>Project domains</th><th>Recommended mentor</th><th>Match & explanation</th><th>Score</th><th>Workload after allocation</th></tr></thead><tbody>
            {rows.map((a) => (
              <tr key={a.team_id} className={a.overload > 0 ? "row-warn" : ""}>
                <td data-label="Team"><div className="cell-title"><b>{a.team_name}</b><span>ID {a.team_id} · {a.project_title}</span></div>
                  {a.change === "reassign" && <Badge value={`was ${a.current_faculty_name}`} tone="info" />}{a.change === "unchanged" && <Badge value="unchanged" tone="neutral" />}</td>
                <td data-label="Domains"><div className="cell-title"><b>{a.team_domain || "—"}</b><span>{a.team_interests.length ? `+ ${a.team_interests.join(", ")}` : "no additional domains"}</span></div></td>
                <td data-label="Mentor"><div className="cell-title"><b>{a.faculty_name}</b></div></td>
                <td data-label="Match"><TierBadge tier={a.tier} />
                  <div className="expl">{a.matched_domains.map((m) => `${m.domain}${m.match === "related" ? " (related to " + m.via + ")" : ""}`).join(", ")}</div>
                  {a.alternative_reason && <div className="why">{a.alternative_reason}</div>}</td>
                <td data-label="Score">{a.score}</td>
                <td data-label="Workload"><UtilBar assigned={a.faculty_current} capacity={a.faculty_capacity} projected={a.faculty_projected} />
                  {a.overload_warning && <div className="small" style={{ color: "var(--bad)", fontWeight: 600 }}><AlertTriangle size={12} aria-hidden /> {a.overload_warning}</div>}</td>
              </tr>))}</tbody></table></div>
        ) : <Empty title={pv.assignments.length ? "No assignments match your filters" : "Nothing to assign"}>{pv.assignments.length ? "Clear the search or filters." : "No eligible team without a guide, or no compatible mentor exists."}</Empty>}
      </Card>

      {proj.length > 0 && (
        <Card title="Mentor workload after this plan">
          <div className="grid g2">{proj.map((p) => (
            <div key={p.faculty_id}><div className="small"><b>{p.name}</b> <span className="muted">· {p.department} · +{p.added} team(s)</span></div><UtilBar assigned={p.current} capacity={p.capacity} projected={p.projected} /></div>))}</div>
        </Card>)}

      {pv.unassigned.length > 0 && (
        <Card title="Teams requiring administrative resolution">
          <div className="table-wrap"><table className="stack"><thead><tr><th>Team</th><th>Domains</th><th>Why</th><th>Closest mentors (override needed)</th><th /></tr></thead><tbody>
            {pv.unassigned.map((u) => (
              <tr key={u.team_id}><td data-label="Team"><div className="cell-title"><b>{u.team_name}</b><span>{u.project_title}</span></div></td>
                <td data-label="Domains"><div className="cell-title"><b>{u.team_domain || "—"}</b><span>{(u.team_interests || []).join(", ")}</span></div></td>
                <td data-label="Why" className="small">{u.reason}{u.keeps_current_mentor && <div className="why">Keeps current mentor: {u.keeps_current_mentor}</div>}</td>
                <td data-label="Closest" className="small">{(u.suggestions || []).map((x) => <div key={x.faculty_id}>{x.name} <span className="muted">({x.assigned}/{x.capacity})</span></div>)}</td>
                <td data-label=""><button className="btn sm" onClick={() => onResolve?.({ id: u.team_id, name: u.team_name })}>Assign manually <ArrowRight size={13} aria-hidden /></button></td></tr>))}</tbody></table></div>
        </Card>)}
    </>
  );
}

function CommitDialog({ pv, onClose, onDone }) {
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const s = pv.summary;
  const needAck = s.new_overload > 0;
  const go = async () => {
    setBusy(true); setErr("");
    try { onDone(await api(`/admin/allocation/preview/${pv.id}/commit`, { method: "POST", body: { confirm: true, acknowledge_overload: ack } })); }
    catch (x) { setErr(x.message); } finally { setBusy(false); }
  };
  const changes = pv.assignments.filter((a) => a.change !== "unchanged").length;
  return (
    <Modal title="Commit allocation" onClose={onClose} dismissible={!busy}
      footer={<><button className="btn" onClick={onClose} disabled={busy}>Cancel</button><Btn className="ok" busy={busy} disabled={needAck && !ack} onClick={go}>Commit {changes} assignment(s)</Btn></>}>
      <p style={{ marginTop: 0 }}>You are about to assign <b>{changes}</b> team(s). Eligibility, domain compatibility and workload are re-checked against fresh data at commit time; anything that changed since the preview is skipped and reported.</p>
      <ul className="small">
        <li>{s.tier_counts.primary} primary · {s.tier_counts.additional} additional · {s.tier_counts.related} related domain matches</li>
        {s.total_overload > 0 && <li><b>{s.total_overload}</b> project(s) above nominal capacity across {s.overloaded_faculty} mentor(s) (worst +{s.max_overload})</li>}
        {pv.unassigned.length > 0 && <li><b>{pv.unassigned.length}</b> team(s) will <b>still require administrative resolution</b>; they are not included</li>}
      </ul>
      {needAck && <Alert tone="warn" strong title="Overload acknowledgement required."><label className="check"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> I have reviewed the overload warnings and accept them</label></Alert>}
      {err && <Alert tone="error">{err}</Alert>}
    </Modal>
  );
}

/* ------------------------------------------------------------------ manual / override */
export function OverrideDialog({ teamId, facultyId, onClose, onDone }) {
  const toast = useToast();
  const { data: c, loading, error } = useAsync(() => api("/admin/allocation/manual-preview", { params: { team_id: teamId, faculty_id: facultyId } }), [teamId, facultyId]);
  const [reason, setReason] = useState("");
  const [ackDomain, setAckDomain] = useState(false);
  const [ackLoad, setAckLoad] = useState(false);
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  if (loading || !c) return <Modal title="Review assignment" onClose={onClose} size="md">{error ? <Alert tone="error">{error}</Alert> : <Skeleton lines={5} />}</Modal>;
  const reasonErr = c.requires_reason && reason.trim().length < 3 ? (c.requires_domain_override ? "A reason is required for an override." : "A reason is required.") : "";
  const ready = c.can_assign && !reasonErr && (!c.requires_domain_override || ackDomain) && (!c.requires_overload_ack || ackLoad);
  const submit = async (e) => {
    e.preventDefault(); setTouched(true);
    if (!ready) return;
    setBusy(true);
    try {
      await api("/admin/allocation/manual", { method: "POST", body: { team_id: teamId, faculty_id: facultyId, reason: reason.trim(), confirm: true, override_domain: ackDomain, acknowledge_overload: ackLoad } });
      toast.success(c.is_override ? "Override assignment saved and recorded in the audit trail." : "Assignment saved."); onDone();
    } catch (x) { toast.error(x.message); } finally { setBusy(false); }
  };
  const list = (a) => (a && a.length ? a.join(", ") : "—");
  return (
    <Modal title={c.is_reassignment ? "Reassign guide" : "Assign guide"} onClose={onClose} size="md" dismissible={!busy}
      footer={<><button type="button" className="btn" onClick={onClose} disabled={busy}>Cancel</button>
        <Btn type="submit" form="override-form" className={c.is_override ? "danger" : "primary"} busy={busy} disabled={!ready}>{c.is_override ? "Confirm override" : c.is_reassignment ? "Reassign" : "Assign"}</Btn></>}>
      <form id="override-form" onSubmit={submit} noValidate>
        <p style={{ marginTop: 0 }}><b>{c.team_name}</b> → <b>{c.faculty_name}</b>{c.current_faculty && <span className="muted"> (currently {c.current_faculty})</span>}</p>
        {c.allocation_finalised && <Alert tone="warn">This allocation is <b>finalised</b>; the change is audited.</Alert>}
        {!c.can_assign && <Alert tone="error" title="Not allowed.">{c.problems.join("; ")}. These mandatory rules cannot be overridden.</Alert>}
        {c.requires_domain_override && <Alert tone="error" strong title="No compatible domain.">{c.faculty_name} has no expertise or supported domain matching this team (primary, additional or related). Assigning them is an <b>administrative override</b> and will be recorded.</Alert>}
        {c.capacity_exceeded && <Alert tone="warn" strong title="Exceeds nominal capacity.">{c.faculty_name} would carry {c.faculty_projected} team(s) against a capacity of {c.faculty_capacity} (overload +{c.projected_overload}).</Alert>}
        {c.domain_compatible && <p className="small"><TierBadge tier={c.match_tier} /> <span className="muted">{c.explanation}</span></p>}
        <div className="compare">
          <div><h4>Team domains</h4><div className="small"><b>Primary:</b> {c.team_domains.primary || "—"}</div><div className="small"><b>Additional:</b> {list(c.team_domains.additional)}</div></div>
          <div><h4>{c.faculty_name}'s domains</h4><div className="small"><b>Expertise:</b> {list(c.faculty_domains.expertise)}</div><div className="small"><b>Supported:</b> {list(c.faculty_domains.supported)}</div><div className="small"><b>Interests:</b> {list(c.faculty_domains.interest)}</div></div>
        </div>
        <div style={{ marginBottom: 14 }}><div className="small muted" style={{ marginBottom: 4 }}>Workload of {c.faculty_name}: now {c.faculty_assigned_before} → after {c.faculty_projected} of {c.faculty_capacity}</div>
          <UtilBar assigned={c.faculty_assigned_before} capacity={c.faculty_capacity} projected={c.faculty_projected} /></div>
        <Field label={c.requires_domain_override ? "Override reason" : "Reason"} required={c.requires_reason} error={touched ? reasonErr : ""} hint={c.requires_reason ? "Recorded in the allocation history and audit log." : "Optional for a standard assignment."}>
          <textarea rows={3} value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} data-autofocus />
        </Field>
        {c.requires_domain_override && <label className="check"><input type="checkbox" checked={ackDomain} onChange={(e) => setAckDomain(e.target.checked)} /> <span><ShieldAlert size={14} aria-hidden /> I confirm this overrides domain compatibility</span></label>}
        {c.requires_overload_ack && <label className="check"><input type="checkbox" checked={ackLoad} onChange={(e) => setAckLoad(e.target.checked)} /> I acknowledge this exceeds the mentor's capacity</label>}
      </form>
    </Modal>
  );
}

function ManualTab({ cid, focusTeam }) {
  const [team, setTeam] = useState(focusTeam);
  const [cands, setCands] = useState(null);
  const [target, setTarget] = useState(null);
  const [k, setK] = useState(0);
  const toast = useToast(), confirm = useConfirm();
  const load = useCallback((p) => api("/admin/teams", { params: { ...p, cycle_id: cid } }), [cid]);
  const fetchCands = useCallback(async (t) => setCands(await api(`/admin/allocation/candidates/${t.id}`)), []);
  React.useEffect(() => { if (focusTeam) { setTeam(focusTeam); fetchCands(focusTeam).catch((e) => toast.error(e.message)); } }, [focusTeam]);   // eslint-disable-line
  const pick = async (t) => { setTeam(t); setCands(null); try { await fetchCands(t); } catch (x) { toast.error(x.message); } };
  const unassign = async () => {
    const r = await confirm({ title: "Remove guide", message: `Remove the guide of ${team.name}? The team returns to the unallocated pool.`, danger: true, reasonRequired: true, reasonLabel: "Reason", confirmLabel: "Remove guide" });
    if (!r) return;
    try { await api("/admin/allocation/unassign", { method: "POST", body: { team_id: team.id, reason: r.reason, confirm: true } }); toast.success("Guide removed"); fetchCands(team); setK(k + 1); } catch (x) { toast.error(x.message); }
  };
  const done = () => { setTarget(null); setK(k + 1); fetchCands(team); };
  return (
    <>
      <Card title="1. Select a team"><DataTable load={load} refreshKey={k} onRow={pick} pageSize={6} searchPlaceholder="Search team or project"
        filters={[{ key: "proposal_status", label: "Proposal", options: ["approved", "allocated", "finalised"] }]}
        columns={[{ key: "name", label: "Team" }, { key: "project_title", label: "Project" }, { key: "proposal_status", label: "Proposal", render: (r) => <Badge value={r.proposal_status} /> }, { key: "guide", label: "Current guide", render: (r) => r.guide || "—" }]} /></Card>
      {team && (
        <Card title={`2. Choose a mentor for ${team.name}`} actions={cands?.team.current_faculty && <button className="btn sm danger" onClick={unassign}>Remove current guide</button>}>
          {!cands ? <Skeleton lines={4} /> : <>
            {cands.team.current_faculty && <Alert tone="info">Current guide: <b>{cands.team.current_faculty}</b> ({cands.team.status}). Choosing another mentor is a reassignment and needs a reason.</Alert>}
            <div className="table-wrap"><table className="stack"><thead><tr><th>Mentor</th><th>Match</th><th>Workload</th><th>Status</th><th /></tr></thead><tbody>
              {cands.faculty.map((f) => (
                <tr key={f.faculty_id}>
                  <td data-label="Mentor"><div className="cell-title"><b>{f.name}</b><span>{f.department}</span></div></td>
                  <td data-label="Match"><TierBadge tier={f.match_tier} /><div className="expl">{f.domain_compatible ? f.explanation : "No domain overlap"}</div></td>
                  <td data-label="Workload"><UtilBar assigned={f.assigned} capacity={f.capacity} projected={f.assigned + 1} /></td>
                  <td data-label="Status" className="small">{f.eligible ? <Badge value="ready" tone="ok" /> : f.blocked ? <span className="muted">Blocked: {f.ineligible_reason}</span> : <Badge value="needs override" tone="warn" />}{!f.eligible && !f.blocked && <div className="muted">{f.ineligible_reason}</div>}</td>
                  <td data-label=""><button className={`btn sm ${f.eligible || f.blocked ? "" : "warn"}`} disabled={f.blocked} onClick={() => setTarget(f.faculty_id)} aria-label={`Review ${f.eligible ? "" : "override of "}assignment to ${f.name}`}>{f.eligible ? "Review…" : "Review override…"}</button></td>
                </tr>))}</tbody></table></div></>}
        </Card>)}
      {target && <OverrideDialog teamId={team.id} facultyId={target} onClose={() => setTarget(null)} onDone={done} />}
    </>
  );
}

/* ------------------------------------------------------------------ lists */
function CurrentTab({ cid }) {
  const load = useCallback((p) => api("/admin/allocation", { params: { ...p, cycle_id: cid } }), [cid]);
  return <Card><DataTable load={load} pageSize={12} searchPlaceholder="Search…" columns={[
    { key: "team_name", label: "Team", render: (r) => <div className="cell-title"><b>{r.team_name}</b><span>{r.project_title}</span></div> },
    { key: "faculty_name", label: "Guide" },
    { key: "match_tier", label: "Match", render: (r) => <TierBadge tier={r.is_override && r.match_tier === "override" ? "override" : r.match_tier} /> },
    { key: "method", label: "Method", render: (r) => <div className="row" style={{ gap: 4 }}><Badge value={r.method} tone="neutral" />{r.is_override && <Badge value="exception" tone="warn" />}</div> },
    { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
    { key: "explanation", label: "Why", render: (r) => <span className="expl">{r.override_reason ? `Override: ${r.override_reason}` : r.explanation}</span> }]} /></Card>;
}

function UnTab({ cid, onResolve }) {
  const { data, loading } = useAsync(() => api("/admin/allocation/unallocated", { params: { cycle_id: cid } }), [cid]);
  if (loading) return <Skeleton lines={5} />;
  const need = data.filter((u) => u.requires_resolution);
  return (
    <>
      {need.length > 0 && <Alert tone="error" title={`${need.length} team(s) have no compatible, eligible mentor.`}>They are never assigned automatically. Use “Assign manually” to apply an administrative override with a recorded reason.</Alert>}
      <Card title={`Teams without a guide (${data.length})`}>{data.length ? <div className="table-wrap"><table className="stack"><thead><tr><th>Team</th><th>Proposal</th><th>Reason</th><th>Closest mentors</th><th /></tr></thead><tbody>
        {data.map((u) => <tr key={u.team_id} className={u.requires_resolution ? "row-bad" : ""}><td data-label="Team"><div className="cell-title"><b>{u.team_name}</b><span>{u.project_title}</span></div></td><td data-label="Proposal"><Badge value={u.proposal_status} /></td><td data-label="Reason" className="small">{u.reason}</td>
          <td data-label="Closest" className="small">{(u.suggestions || []).map((x) => <div key={x.faculty_id}>{x.name} <span className="muted">({x.assigned}/{x.capacity})</span></div>)}</td>
          <td data-label="">{u.requires_resolution && <button className="btn sm" onClick={() => onResolve({ id: u.team_id, name: u.team_name })}>Assign manually <ArrowRight size={13} aria-hidden /></button>}</td></tr>)}</tbody></table></div> : <Empty title="Every team has a guide">Nothing is waiting for allocation.</Empty>}</Card>
    </>
  );
}

function FinaliseTab({ cid }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [block, setBlock] = useState(null);
  const run = async () => {
    setBusy(true);
    try { const r = await api("/admin/allocation/finalise", { method: "POST", body: { confirm: true, cycle_id: cid, acknowledge_overload: ack } }); setOpen(false); setBlock(null); toast.success(`${r.finalised} allocation(s) finalised`); }
    catch (x) { setBlock(x.detail && typeof x.detail === "object" ? x.detail : { message: x.message, problems: [] }); if (!x.detail?.acknowledgeable) toast.error(x.message); }
    finally { setBusy(false); }
  };
  return (
    <Card title="Finalise this cycle">
      <p>Before finalising, the system re-validates every assignment: faculty still approved and active, proposals still eligible and no duplicates. Overload (mentors above capacity) must be acknowledged explicitly.</p>
      {block && <Alert tone={block.acknowledgeable ? "warn" : "error"} strong title={block.acknowledgeable ? "Mentors are above capacity." : "Finalisation blocked."}>
        <ul style={{ margin: ".3rem 0 0 1rem", padding: 0 }}>{(block.problems || [block.message]).map((p) => <li key={p}>{p}</li>)}</ul></Alert>}
      <button className="btn danger" onClick={() => { setOpen(true); setAck(!!block?.acknowledgeable); }}>Finalise allocation…</button>
      {open && <Modal title="Finalise allocation" onClose={() => setOpen(false)} dismissible={!busy}
        footer={<><button className="btn" onClick={() => setOpen(false)} disabled={busy}>Cancel</button><Btn className="danger" busy={busy} disabled={block?.acknowledgeable && !ack} onClick={run}>Finalise</Btn></>}>
        <Alert tone="warn" title="This makes the current assignments official.">Automatic re-runs are disabled afterwards; any later change needs a manual reassignment with a reason (audited).</Alert>
        {block?.acknowledgeable && <label className="check"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> I acknowledge the overload listed above and want to finalise anyway</label>}
      </Modal>}
    </Card>
  );
}
