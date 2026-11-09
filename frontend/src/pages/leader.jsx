import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Plus, Trash2, Save, UsersRound, FileText, UserCheck, CheckCircle2, Target } from "lucide-react";
import { api, fmt, fmtDate } from "../api.js";
import { Badge, Card, Empty, Field, MultiSelect, PageHead, Spinner, Stat, useAsync, useConfirm, useDomains, useToast } from "../ui.jsx";
import { regnoError } from "../regno.js";
import { emailError } from "../email.js";

const useTeam = () => useAsync(() => api("/team"), []);

function Locked({ team }) {
  if (team.editable) return <div className="alert info">You can edit until you submit the proposal{team.cycle.proposal_deadline ? ` (deadline ${fmt(team.cycle.proposal_deadline)})` : ""}.</div>;
  return <div className="alert warn">{team.edit_block_reason}</div>;
}

export function LeaderDashboard() {
  const { data: t, loading, error } = useTeam();
  const { data: notes } = useAsync(() => api("/notifications", { params: { page_size: 5 } }), []);
  if (loading) return <Spinner />;
  if (error) return <div className="alert error">{error}</div>;
  const p = t.proposal, g = t.allocation;
  return (
    <>
      <PageHead title={t.name} sub={`${t.department} · ${t.programme} · ${t.cycle.name}`} />
      <div className="stats">
        <Stat label="Team members" icon={UsersRound} value={t.members.length} />
        <Stat label="Proposal status" icon={FileText} value={<Badge value={p.status} />} tone={p.status === "rejected" ? "bad" : p.status === "approved" ? "ok" : "warn"} />
        <Stat label="Allocated guide" icon={UserCheck} value={g ? g.faculty.name : "Not yet"} tone={g ? "ok" : ""} sub={g ? `Status: ${g.status}` : "Awaiting allocation"} />
      </div>
      {p.status === "needs_revision" && <div className="alert warn"><b>Revision requested:</b> {p.admin_remarks} <Link to="/team/proposal">Edit proposal</Link></div>}
      {p.status === "draft" && <div className="alert info">Your proposal is still a draft. <Link to="/team/proposal">Complete and submit it</Link>.</div>}
      <div className="grid g2">
        <Card title="Project" actions={<Link className="btn sm" to="/team/proposal">Open</Link>}>
          <dl className="kv"><dt>Title</dt><dd>{p.title || "—"}</dd><dt>Primary domain</dt><dd>{p.primary_domain?.name || "—"}</dd><dt>Eligible for allocation</dt><dd>{p.eligible_for_allocation ? "Yes" : "No"}</dd></dl>
        </Card>
        <Card title="Latest notifications" actions={<Link className="btn sm" to="/team/notifications">All</Link>}>
          {notes?.items.length ? notes.items.map((n) => <div key={n.id} className={`notif ${n.is_read ? "" : "unread"}`}><div><b>{n.title}</b><div className="small muted">{n.message}</div></div></div>) : <Empty>No notifications yet.</Empty>}
        </Card>
      </div>
    </>
  );
}

const blankMember = { full_name: "", email: "", registration_number: "", department: "", programme: "", year_semester: "" };

export function LeaderTeam() {
  const { data: t, loading, error, reload } = useTeam();
  const toast = useToast(), confirm = useConfirm();
  const [nm, setNm] = useState(null);
  const [edit, setEdit] = useState({});
  const [cr, setCr] = useState("");
  const [crs, setCrs] = useState([]);
  useEffect(() => { api("/team/change-requests").then(setCrs).catch(() => {}); }, [t]);
  if (loading) return <Spinner />;
  if (error) return <div className="alert error">{error}</div>;
  const run = async (fn, msg) => { try { await fn(); toast.success(msg); setNm(null); setEdit({}); reload(); } catch (x) { toast.error(x.message); } };
  const remove = async (m) => { if (await confirm({ title: "Remove member", message: `Remove ${m.full_name} (${m.registration_number}) from the team?`, danger: true, confirmLabel: "Remove" })) run(() => api(`/team/members/${m.id}`, { method: "DELETE" }), "Member removed"); };
  return (
    <>
      <PageHead title="Team details" sub={`${t.name} · ${t.cycle.name}`} />
      <Locked team={t} />
      <Card title="Team">
        <dl className="kv"><dt>Name</dt><dd>{t.name}</dd><dt>Department</dt><dd>{t.department}</dd><dt>Programme</dt><dd>{t.programme}</dd><dt>Year / semester</dt><dd>{t.year_semester || "—"}</dd><dt>Leader</dt><dd>{t.leader.name} ({t.leader.email})</dd></dl>
      </Card>
      <Card title={`Members (${t.members.length})`} actions={t.editable && <button className="btn sm primary" onClick={() => setNm({ ...blankMember })}><Plus size={14} /> Add member</button>}>
        <div className="table-wrap"><table><thead><tr><th>Name</th><th>Registration no.</th><th>E-mail</th><th>Dept / programme</th><th>Year</th><th /></tr></thead><tbody>
          {t.members.map((m) => (
            <tr key={m.id}>
              <td>{m.full_name} {m.is_leader && <Badge value="leader" tone="ok" />}</td><td>{m.registration_number}</td><td>{m.email}</td><td>{m.department} / {m.programme}</td><td>{m.year_semester || "—"}</td>
              <td>{t.editable && <div className="row"><button className="btn sm" onClick={() => setEdit(m)}>Edit</button>{!m.is_leader && <button className="btn sm" onClick={() => remove(m)} aria-label={`Remove ${m.full_name}`}><Trash2 size={14} /></button>}</div>}</td>
            </tr>))}
        </tbody></table></div>
      </Card>
      {(nm || edit.id) && (
        <Card title={nm ? "Add member" : `Edit ${edit.full_name}`}>
          {(() => { const v = nm || edit; const set = (k) => (e) => (nm ? setNm({ ...nm, [k]: e.target.value }) : setEdit({ ...edit, [k]: e.target.value }));
            return (<form onSubmit={(e) => { e.preventDefault(); const body = { full_name: v.full_name, email: v.email, registration_number: v.registration_number, department: v.department || undefined, programme: v.programme || undefined, year_semester: v.year_semester || undefined };
              if (nm) { const re = regnoError(v.registration_number) || emailError(v.email); if (re) return toast.error(re); run(() => api("/team/members", { method: "POST", body }), "Member added"); } else { if (v.is_leader) delete body.email; run(() => api(`/team/members/${v.id}`, { method: "PUT", body }), "Member updated"); } }}>
              <div className="form-grid">
                <Field label="Full name" required><input required value={v.full_name} onChange={set("full_name")} /></Field>
                <Field label="E-mail" required hint={v.is_leader ? "The leader's login e-mail cannot be changed here." : undefined}><input type="email" required disabled={!!v.is_leader} value={v.email} onChange={set("email")} /></Field>
                <Field label="Registration number" required hint="Format: RA{BATCH}11003040{NNN}, e.g. RA2311003040001"><input required value={v.registration_number} onChange={set("registration_number")} /></Field>
                <Field label="Year / semester"><input value={v.year_semester} onChange={set("year_semester")} /></Field>
                <Field label="Department"><input value={v.department} onChange={set("department")} /></Field>
                <Field label="Programme"><input value={v.programme} onChange={set("programme")} /></Field>
              </div>
              <div className="row"><button className="btn primary"><Save size={14} /> Save</button><button type="button" className="btn" onClick={() => { setNm(null); setEdit({}); }}>Cancel</button></div>
            </form>); })()}
        </Card>)}
      {t.editable && (
        <Card title="Edit team information">
          <form onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.target); run(() => api("/team", { method: "PUT", body: { name: f.get("name"), department: f.get("department"), programme: f.get("programme"), year_semester: f.get("year_semester") } }), "Team updated"); }}>
            <div className="form-grid">
              <Field label="Team name"><input name="name" defaultValue={t.name} required /></Field><Field label="Year / semester"><input name="year_semester" defaultValue={t.year_semester} /></Field>
              <Field label="Department"><input name="department" defaultValue={t.department} required /></Field><Field label="Programme"><input name="programme" defaultValue={t.programme} required /></Field>
            </div><button className="btn primary">Save changes</button>
          </form>
        </Card>)}
      {t.edit_block_code === "finalised" && (
        <Card title="Request a membership change">
          <p className="muted small">Allocation is final. Describe the change you need; an administrator reviews and applies it.</p>
          <Field label="Request"><textarea rows={3} value={cr} onChange={(e) => setCr(e.target.value)} /></Field>
          <button className="btn primary" disabled={cr.trim().length < 10} onClick={() => run(async () => { await api("/team/change-requests", { method: "POST", body: { description: cr } }); setCr(""); }, "Request sent")}>Send request</button>
          {crs.length > 0 && <div className="table-wrap" style={{ marginTop: 12 }}><table><thead><tr><th>Request</th><th>Status</th><th>Admin remarks</th></tr></thead><tbody>{crs.map((c) => <tr key={c.id}><td>{c.description}</td><td><Badge value={c.status} /></td><td>{c.admin_remarks || "—"}</td></tr>)}</tbody></table></div>}
        </Card>)}
    </>
  );
}

export function LeaderProposal() {
  const { data: t, loading, error, reload } = useTeam();
  const domains = useDomains();
  const toast = useToast(), confirm = useConfirm();
  const [f, setF] = useState(null);
  const [errs, setErrs] = useState({});
  useEffect(() => {
    if (!t) return;
    const p = t.proposal;
    setF({ title: p.title, description: p.description, primary: p.primary_domain?.is_custom ? domains.find((d) => d.is_other)?.id ?? "" : p.primary_domain?.id ?? "",
      interests: p.interest_domains.filter((d) => !d.is_custom).map((d) => d.id), custom: p.primary_domain?.is_custom ? p.primary_domain.name : (p.interest_domains.find((d) => d.is_custom)?.name || ""),
      customInInterest: !!p.interest_domains.find((d) => d.is_custom), tech: (p.technologies || []).join(", "), objectives: p.objectives, outcomes: p.expected_outcomes });
  }, [t, domains.length]);
  if (loading || !f) return <Spinner />;
  if (error) return <div className="alert error">{error}</div>;
  const other = domains.find((d) => d.is_other)?.id;
  const needsCustom = f.primary === other || f.interests.includes(other) || f.customInInterest;
  const opts = domains.map((d) => ({ value: d.id, label: d.name }));
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const body = () => ({ title: f.title, description: f.description, primary_domain_id: f.primary ? Number(f.primary) : null,
    interest_domain_ids: f.interests.concat(f.customInInterest && other && !f.interests.includes(other) ? [other] : []),
    custom_domain_name: needsCustom ? f.custom : null, technologies: f.tech.split(",").map((s) => s.trim()).filter(Boolean), objectives: f.objectives, expected_outcomes: f.outcomes });
  const validate = () => { const e = {}; if (needsCustom && f.custom.trim().length < 3) e.custom = "Enter your custom domain name"; setErrs(e); return !Object.keys(e).length; };
  const save = async (submit) => {
    if (!validate()) return;
    try {
      await api("/team/proposal", { method: "PUT", body: body() });
      if (submit) {
        if (!(await confirm({ title: "Submit proposal", message: "After submitting you cannot edit the team or proposal unless the administrator requests a revision. Submit now?", confirmLabel: "Submit" }))) { reload(); return; }
        await api("/team/proposal/submit", { method: "POST" });
      }
      toast.success(submit ? "Proposal submitted" : "Draft saved"); reload();
    } catch (x) { toast.error(x.message); }
  };
  const p = t.proposal;
  return (
    <>
      <PageHead title="Project proposal" sub="One proposal is shared by the whole team." actions={<Badge value={p.status} />} />
      <Locked team={t} />
      {p.admin_remarks && <div className={`alert ${p.status === "rejected" ? "error" : "warn"}`}><b>Administrator feedback:</b> {p.admin_remarks}</div>}
      <Card>
        <fieldset disabled={!t.editable} style={{ border: 0, padding: 0, margin: 0 }}>
          <Field label="Project title" required><input value={f.title} onChange={set("title")} maxLength={250} /></Field>
          <Field label="Project description" required hint="At least 30 characters."><textarea rows={6} value={f.description} onChange={set("description")} /></Field>
          <Field label="Primary domain" required><select value={f.primary} onChange={set("primary")}><option value="">Select…</option>{opts.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select></Field>
          <MultiSelect label="Additional interests (domains)" options={opts.filter((o) => o.value !== Number(f.primary))} value={f.interests} onChange={(v) => setF({ ...f, interests: v })} max={15} />
          {needsCustom && <Field label="Custom domain name" required error={errs.custom} hint="Shown because “Other” is selected; saved for admin review."><input value={f.custom} onChange={set("custom")} /></Field>}
          <Field label="Technologies / tools" hint="Comma-separated, e.g. React, FastAPI, MySQL"><input value={f.tech} onChange={set("tech")} /></Field>
          <Field label="Objectives (optional)"><textarea rows={3} value={f.objectives} onChange={set("objectives")} /></Field>
          <Field label="Expected outcomes (optional)"><textarea rows={3} value={f.outcomes} onChange={set("outcomes")} /></Field>
          <div className="row"><button className="btn" onClick={() => save(false)}>Save draft</button><button className="btn primary" onClick={() => save(true)}>Save &amp; submit</button></div>
        </fieldset>
      </Card>
    </>
  );
}

const STEPS = ["draft", "submitted", "under_review", "approved", "allocated", "finalised"];
export function LeaderStatus() {
  const { data: t, loading } = useTeam();
  if (loading) return <Spinner />;
  const p = t.proposal;
  return (
    <>
      <PageHead title="Proposal & registration status" />
      <div className="stats">
        <Stat label="Registration" icon={CheckCircle2} value="Registered" tone="ok" sub={fmtDate(t.created_at)} />
        <Stat label="Proposal" icon={FileText} value={<Badge value={p.status} />} />
        <Stat label="Eligible for allocation" icon={Target} value={p.eligible_for_allocation ? "Yes" : "No"} tone={p.eligible_for_allocation ? "ok" : "warn"} />
      </div>
      <Card title="Progress">
        <div className="row">{STEPS.map((s) => <Badge key={s} value={s} tone={STEPS.indexOf(s) <= STEPS.indexOf(p.status) && !["rejected", "needs_revision"].includes(p.status) ? "ok" : "muted"} />)}</div>
        {["rejected", "needs_revision"].includes(p.status) && <div className="alert warn" style={{ marginTop: 12 }}>Current status: <b>{p.status.replace("_", " ")}</b>. {p.admin_remarks}</div>}
      </Card>
      <Card title="Review history">
        {p.reviews.length ? <div className="timeline">{[...p.reviews].reverse().map((r) => <div key={r.id}><b>{r.from_status.replace("_", " ")} → {r.to_status.replace("_", " ")}</b><div className="small muted">{fmt(r.created_at)}</div><div>{r.remarks}</div></div>)}</div> : <Empty>No review activity yet.</Empty>}
      </Card>
    </>
  );
}

export function LeaderGuide() {
  const { data: t, loading } = useTeam();
  if (loading) return <Spinner />;
  const g = t.allocation;
  return (
    <>
      <PageHead title="Allocated guide" />
      {!g ? <Card><Empty>No guide has been allocated yet. You will be notified when allocation happens.</Empty></Card> : (
        <Card title={g.faculty.name} actions={<Badge value={g.status} />}>
          <dl className="kv"><dt>Designation</dt><dd>{g.faculty.designation}</dd><dt>Department</dt><dd>{g.faculty.department}</dd><dt>E-mail</dt><dd>{g.faculty.email}</dd><dt>Assigned</dt><dd>{fmt(g.assigned_at)}</dd><dt>Applies to</dt><dd>All {t.members.length} team members share this guide.</dd></dl>
          {g.status !== "finalised" && <div className="alert info" style={{ marginTop: 12 }}>This allocation is not final yet; the administrator may still adjust it.</div>}
        </Card>)}
    </>
  );
}
