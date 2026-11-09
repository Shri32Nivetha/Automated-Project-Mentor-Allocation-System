import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { UserCheck, UsersRound, Gauge, Target } from "lucide-react";
import { api, fmt } from "../api.js";
import { Badge, Card, Empty, Field, MultiSelect, PageHead, Spinner, Stat, useAsync, useDomains, useToast } from "../ui.jsx";

const useMe = () => useAsync(() => api("/faculty/me"), []);

function Pending({ me }) {
  if (me.approval_status === "approved") return null;
  return <div className={`alert ${me.approval_status === "rejected" ? "error" : "warn"}`}>Your registration is <b>{me.approval_status}</b>. {me.approval_status === "pending" ? "You will not be assigned teams until an administrator approves it." : me.approval_remarks}</div>;
}

export function FacultyDashboard() {
  const { data: me, loading, error } = useMe();
  const { data: teams } = useAsync(() => api("/faculty/me/teams"), []);
  if (loading) return <Spinner />;
  if (error) return <div className="alert error">{error}</div>;
  const w = me.workload;
  return (
    <>
      <PageHead title={`Welcome, ${me.full_name}`} sub={`${me.designation} · ${me.department}`} />
      <Pending me={me} />
      <div className="stats">
        <Stat label="Approval status" icon={UserCheck} value={<Badge value={me.approval_status} />} />
        <Stat label="Assigned teams" icon={UsersRound} value={w ? w.assigned : "—"} sub={w?.cycle.name} />
        <Stat label="Maximum capacity" icon={Gauge} value={w ? w.max_capacity : "—"} sub="team projects" />
        <Stat label="Remaining capacity" icon={Target} value={w ? w.remaining : "—"} tone={w?.over_capacity ? "bad" : "ok"} />
      </div>
      <Card title="Assigned teams" actions={<Link className="btn sm" to="/faculty/teams">View all</Link>}>
        {teams?.length ? teams.slice(0, 5).map((t) => <div key={t.team.id + t.cycle.id} className="notif"><div><b>{t.team.name}</b><div className="small muted">{t.proposal.title} · {t.cycle.name}</div></div><Badge value={t.allocation_status} /></div>) : <Empty>No teams assigned yet.</Empty>}
      </Card>
    </>
  );
}

export function FacultyProfilePage() {
  const { data: me, loading, error, reload } = useMe();
  const domains = useDomains();
  const toast = useToast();
  const [f, setF] = useState(null);
  const [exp, setExp] = useState([]), [sup, setSup] = useState([]), [int, setInt] = useState([]);
  const [custom, setCustom] = useState("");
  useEffect(() => {
    if (!me) return;
    setF({ full_name: me.full_name, department: me.department, additional_interests: me.additional_interests, is_available: me.is_available });
    const ids = (l) => l.filter((d) => !d.is_custom).map((d) => d.id);
    const oth = domains.find((d) => d.is_other)?.id;
    const cust = [...me.domains.expertise, ...me.domains.supported, ...me.domains.interest].find((d) => d.is_custom);
    const addOther = (l) => (l.some((d) => d.is_custom) && oth ? [oth] : []);
    setExp(ids(me.domains.expertise).concat(addOther(me.domains.expertise))); setSup(ids(me.domains.supported).concat(addOther(me.domains.supported))); setInt(ids(me.domains.interest).concat(addOther(me.domains.interest)));
    setCustom(cust?.name || "");
  }, [me, domains.length]);
  if (loading || !f) return <Spinner />;
  if (error) return <div className="alert error">{error}</div>;
  const opts = domains.map((d) => ({ value: d.id, label: d.name }));
  const oth = domains.find((d) => d.is_other)?.id;
  const needsCustom = [exp, sup, int].some((l) => l.includes(oth));
  const save = async (e) => {
    e.preventDefault();
    if (needsCustom && custom.trim().length < 3) return toast.error("Enter your custom domain name.");
    try { await api("/faculty/me", { method: "PUT", body: { ...f, expertise_domain_ids: exp, supported_domain_ids: sup, interest_domain_ids: int, custom_domain_name: needsCustom ? custom : null } }); toast.success("Profile updated"); reload(); } catch (x) { toast.error(x.message); }
  };
  return (
    <>
      <PageHead title="Profile & expertise" actions={<Badge value={me.approval_status} />} />
      <Pending me={me} />
      <Card title="Account"><dl className="kv"><dt>E-mail</dt><dd>{me.email}</dd><dt>Employee ID</dt><dd>{me.employee_id}</dd><dt>Designation</dt><dd>{me.designation}</dd><dt>Capacity</dt><dd>{me.workload ? `${me.workload.max_capacity} team projects` : "—"} <span className="muted small">({me.capacity_note})</span></dd></dl></Card>
      <Card title="Edit profile">
        <form onSubmit={save}>
          <div className="form-grid">
            <Field label="Full name"><input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
            <Field label="Department"><input value={f.department} onChange={(e) => setF({ ...f, department: e.target.value })} /></Field>
            <Field label="Availability"><select value={String(f.is_available)} onChange={(e) => setF({ ...f, is_available: e.target.value === "true" })}><option value="true">Available</option><option value="false">Not available</option></select></Field>
          </div>
          <MultiSelect label="Areas of expertise" options={opts} value={exp} onChange={setExp} />
          <MultiSelect label="Supported project domains" options={opts} value={sup} onChange={setSup} />
          <MultiSelect label="Additional interests" options={opts} value={int} onChange={setInt} />
          {needsCustom && <Field label="Custom domain name" required><input value={custom} onChange={(e) => setCustom(e.target.value)} /></Field>}
          <Field label="Other interests"><textarea rows={2} value={f.additional_interests} onChange={(e) => setF({ ...f, additional_interests: e.target.value })} /></Field>
          <button className="btn primary">Save profile</button>
        </form>
      </Card>
    </>
  );
}

export function FacultyTeams() {
  const { data, loading, error } = useAsync(() => api("/faculty/me/teams"), []);
  if (loading) return <Spinner />;
  if (error) return <div className="alert error">{error}</div>;
  return (
    <>
      <PageHead title="Assigned teams" />
      {!data.length && <Card><Empty>No teams are assigned to you yet.</Empty></Card>}
      {data.map((t) => (
        <Card key={t.team.id} title={`${t.team.name} — ${t.cycle.name}`} actions={<Badge value={t.allocation_status} />}>
          <h3>{t.proposal.title}</h3>
          <p className="muted small">Domain: {t.proposal.primary_domain?.name || "—"} · Technologies: {(t.proposal.technologies || []).join(", ") || "—"}</p>
          <p style={{ whiteSpace: "pre-line" }}>{t.proposal.description}</p>
          {t.proposal.objectives && <p><b>Objectives:</b> {t.proposal.objectives}</p>}
          {t.proposal.expected_outcomes && <p><b>Expected outcomes:</b> {t.proposal.expected_outcomes}</p>}
          <div className="table-wrap"><table><thead><tr><th>Member</th><th>Reg. no.</th><th>E-mail</th><th>Dept / programme</th></tr></thead><tbody>
            {t.team.members.map((m) => <tr key={m.id}><td>{m.full_name} {m.is_leader && <Badge value="leader" tone="ok" />}</td><td>{m.registration_number}</td><td>{m.email}</td><td>{m.department} / {m.programme}</td></tr>)}
          </tbody></table></div>
        </Card>))}
    </>
  );
}

export function FacultyWorkload() {
  const { data: me, loading } = useMe();
  const { data: teams } = useAsync(() => api("/faculty/me/teams"), []);
  if (loading) return <Spinner />;
  const w = me.workload;
  return (
    <>
      <PageHead title="Workload & capacity" sub="Capacity counts team projects, not individual students." />
      {!w ? <Card><Empty>No allocation cycle is active.</Empty></Card> : (
        <>
          <div className="stats"><Stat label="Assigned (team projects)" icon={UsersRound} value={w.assigned} /><Stat label="Maximum capacity" icon={Gauge} value={w.max_capacity} /><Stat label="Remaining" icon={Target} value={w.remaining} tone={w.over_capacity ? "bad" : "ok"} /></div>
          <Card title={w.cycle.name}>
            <div className={`bar ${w.over_capacity ? "over" : ""}`} role="img" aria-label={`${w.assigned} of ${w.max_capacity}`}><div style={{ width: `${w.max_capacity ? Math.min(100, (w.assigned / w.max_capacity) * 100) : 0}%` }} /></div>
            <p className="small muted">{w.can_receive_new ? "You can receive new teams." : `You cannot currently receive new teams: ${w.ineligible_reason}.`} Only an administrator can change your capacity.</p>
            {w.over_capacity && <div className="alert warn">You supervise more teams than your current capacity. Existing assignments stay until an administrator reassigns them.</div>}
          </Card>
        </>)}
      <Card title="Your teams (all cycles)">{teams?.length ? teams.map((t) => <div className="notif" key={t.team.id}><span>{t.team.name} <span className="muted small">({t.cycle.name}, {t.team.members.length} students)</span></span><span className="small muted">{fmt(t.assigned_at)}</span></div>) : <Empty>None yet.</Empty>}</Card>
    </>
  );
}
