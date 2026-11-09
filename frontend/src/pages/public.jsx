import React, { useEffect, useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { Plus, Trash2, GraduationCap, Users, Scale, ShieldCheck } from "lucide-react";
import { api } from "../api.js";
import { regnoError } from "../regno.js";
import { emailError } from "../email.js";
import { useAuth } from "../auth.jsx";
import { Field, MultiSelect, Spinner, useDomains, useToast } from "../ui.jsx";

export const homeFor = (u) => (u.role === "admin" ? "/admin" : u.role === "faculty" ? "/faculty" : "/team");

function AuthLayout({ children, wide }) {
  return (
    <div className="auth-wrap">
      <aside className="auth-side">
        <div className="brand" style={{ padding: 0 }}><span className="logo"><GraduationCap size={18} aria-hidden /></span><span>GuideAllocate<small>Project guide allocation</small></span></div>
        <div>
          <h1>Project guide allocation for your college</h1>
          <p className="auth-lede">Match every project team with the right faculty mentor, fairly and transparently.</p>
          <div className="feature"><span><Users size={17} aria-hidden /></span><div><b>One team registration — only the team leader needs a login</b><small>Members are recorded once and share a single proposal.</small></div></div>
          <div className="feature"><span><Scale size={17} aria-hidden /></span><div><b>Optimised, explainable guide matching by domain and workload</b><small>Every recommendation shows why a mentor was chosen.</small></div></div>
          <div className="feature"><span><ShieldCheck size={17} aria-hidden /></span><div><b>Faculty capacity counted in team projects, with a full audit trail</b><small>Each change is recorded and reviewable by administrators.</small></div></div>
        </div>
        <div className="auth-foot">Project Guide Allocation System</div>
      </aside>
      <main className="auth-main"><div className={`card auth-card ${wide ? "wide" : ""}`}>{children}</div></main>
    </div>
  );
}

export function Login() {
  const { user, login, expired } = useAuth();
  const nav = useNavigate();
  const [f, setF] = useState({ email: "", password: "" });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to={homeFor(user)} replace />;
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setErr("");
    try { nav(homeFor(await login(f.email, f.password))); } catch (x) { setErr(x.message); } finally { setBusy(false); }
  };
  return (
    <AuthLayout>
      <h2>Sign in</h2>
      <p className="muted">Team leaders, faculty and administrators sign in here.</p>
      {expired && <div className="alert warn">Your session expired. Please sign in again.</div>}
      {err && <div className="alert error" role="alert">{err}</div>}
      <form onSubmit={submit}>
        <Field label="Institutional e-mail" required><input type="email" autoComplete="username" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
        <Field label="Password" required><input type="password" autoComplete="current-password" required value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
        <button className="btn primary" style={{ width: "100%", justifyContent: "center" }} disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
      <p className="small">New team? <Link to="/register/team">Register your team</Link> · Faculty? <Link to="/register/faculty">Register as faculty</Link></p>
      <p className="small"><Link to="/reset-password">Forgot password?</Link></p>
    </AuthLayout>
  );
}

export function ResetPassword() {
  const [sp] = useSearchParams();
  const toast = useToast();
  const nav = useNavigate();
  const [token, setToken] = useState(sp.get("token") || "");
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const request = async (e) => { e.preventDefault(); setErr(""); try { setMsg((await api("/auth/password-reset/request", { method: "POST", body: { email } })).message); } catch (x) { setErr(x.message); } };
  const confirm = async (e) => { e.preventDefault(); setErr(""); try { await api("/auth/password-reset/confirm", { method: "POST", body: { token, new_password: pw } }); toast.success("Password updated. Please sign in."); nav("/login"); } catch (x) { setErr(x.message); } };
  return (
    <AuthLayout>
      <h2>Reset password</h2>
      {err && <div className="alert error">{err}</div>}
      {msg && <div className="alert info">{msg}</div>}
      <form onSubmit={request}>
        <Field label="Your e-mail"><input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <button className="btn">Request reset link</button>
      </form>
      <hr />
      <p className="muted small">Already have a token (e-mailed, or given to you by the administrator)?</p>
      <form onSubmit={confirm}>
        <Field label="Reset token"><input required value={token} onChange={(e) => setToken(e.target.value)} /></Field>
        <Field label="New password" hint="At least 8 characters with letters and numbers."><input type="password" required value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
        <button className="btn primary">Set new password</button>
      </form>
      <p className="small"><Link to="/login">Back to sign in</Link></p>
    </AuthLayout>
  );
}

const emptyMember = () => ({ full_name: "", email: "", registration_number: "", department: "", programme: "", year_semester: "" });
const PW_RE = /^(?=.*[A-Za-z])(?=.*\d).{8,}$/;

export function TeamRegister() {
  const nav = useNavigate();
  const toast = useToast();
  const [meta, setMeta] = useState(null);
  const [team, setTeam] = useState({ team_name: "", department: "", programme: "", year_semester: "" });
  const [leader, setLeader] = useState({ ...emptyMember(), password: "" });
  const [members, setMembers] = useState([emptyMember()]);
  const [errors, setErrors] = useState({});
  const [serverErr, setServerErr] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api("/meta").then(setMeta); }, []);
  if (!meta) return <AuthLayout><Spinner /></AuthLayout>;
  const { min_team_size: min, max_team_size: max, allow_cross_department: xd, allow_cross_programme: xp, allowed_email_domains: doms } = meta.team_rules;
  const total = members.length + 1;
  const upd = (i, k, v) => setMembers(members.map((m, j) => (j === i ? { ...m, [k]: v } : m)));
  const validate = () => {
    const e = {};
    const need = (key, v, label) => { if (!String(v || "").trim()) e[key] = `${label} is required`; };
    need("team_name", team.team_name, "Team name"); need("department", team.department, "Department"); need("programme", team.programme, "Programme");
    const people = [["leader", leader], ...members.map((m, i) => [`m${i}`, m])];
    const seenE = new Map(), seenR = new Map();
    const allowed = String(doms || "").split(",").map((d) => d.trim().toLowerCase().replace(/^@/, "")).filter(Boolean);
    people.forEach(([k, p]) => {
      need(`${k}.full_name`, p.full_name, "Name"); need(`${k}.email`, p.email, "E-mail"); need(`${k}.registration_number`, p.registration_number, "Registration number");
      const em = p.email.trim().toLowerCase(), rg = p.registration_number.replace(/\s+/g, "").toUpperCase();
      if (em && emailError(em)) e[`${k}.email`] = emailError(em);
      else if (em && allowed.length && !allowed.includes(em.split("@")[1])) e[`${k}.email`] = `Use an institutional e-mail (${allowed.join(", ")})`;
      if (rg && !e[`${k}.registration_number`]) { const re = regnoError(rg); if (re) e[`${k}.registration_number`] = re; }
      if (em && seenE.has(em)) e[`${k}.email`] = "Duplicate e-mail in this team"; else if (em) seenE.set(em, k);
      if (rg && seenR.has(rg)) e[`${k}.registration_number`] = "Duplicate registration number in this team"; else if (rg) seenR.set(rg, k);
      if (k !== "leader") {
        if (!xd && p.department.trim() && p.department.trim().toLowerCase() !== team.department.trim().toLowerCase()) e[`${k}.department`] = "Must match the team department";
        if (!xp && p.programme.trim() && p.programme.trim().toLowerCase() !== team.programme.trim().toLowerCase()) e[`${k}.programme`] = "Must match the team programme";
      }
    });
    if (!PW_RE.test(leader.password)) e["leader.password"] = "At least 8 characters with letters and numbers";
    if (total < min || total > max) e.size = `A team needs ${min}–${max} students including the leader (currently ${total}).`;
    return e;
  };
  const submit = async (ev) => {
    ev.preventDefault(); setServerErr("");
    const e = validate(); setErrors(e);
    if (Object.keys(e).length) { toast.error("Please fix the highlighted fields."); return; }
    setBusy(true);
    const clean = (p) => ({ ...p, department: p.department.trim() || undefined, programme: p.programme.trim() || undefined, year_semester: p.year_semester.trim() || undefined });
    try {
      await api("/register/team", { method: "POST", body: { ...team, number_of_members: total, leader: { ...clean(leader), department: leader.department.trim() || team.department, programme: leader.programme.trim() || team.programme }, members: members.map(clean) } });
      toast.success("Team registered. You can now sign in as the team leader."); nav("/login");
    } catch (x) { setServerErr(x.message); window.scrollTo({ top: 0 }); } finally { setBusy(false); }
  };
  const E = (k) => errors[k];
  return (
    <AuthLayout wide>
      <h2>Register your team</h2>
      {meta.active_cycle ? <p className="muted">Allocation cycle: <b>{meta.active_cycle.name}</b>. Only the team leader gets a login; other members are stored as team records.</p>
        : <div className="alert warn">No allocation cycle is open. Registration is currently unavailable.</div>}
      {serverErr && <div className="alert error" role="alert">{serverErr}</div>}
      {E("size") && <div className="alert error" role="alert">{E("size")}</div>}
      <form onSubmit={submit} noValidate>
        <h3>Team</h3>
        <div className="form-grid" style={{ marginTop: ".6rem" }}>
          <Field label="Team name" error={E("team_name")} required><input value={team.team_name} onChange={(e) => setTeam({ ...team, team_name: e.target.value })} /></Field>
          <Field label="Year / semester"><input value={team.year_semester} onChange={(e) => setTeam({ ...team, year_semester: e.target.value })} placeholder="e.g. Year 4 / Sem 7" /></Field>
          <Field label="Department" error={E("department")} required><input value={team.department} onChange={(e) => setTeam({ ...team, department: e.target.value })} /></Field>
          <Field label="Degree / programme" error={E("programme")} required><input value={team.programme} onChange={(e) => setTeam({ ...team, programme: e.target.value })} /></Field>
        </div>
        <h3>Team leader (creates the login)</h3>
        <div className="form-grid" style={{ marginTop: ".6rem" }}>
          <Field label="Full name" error={E("leader.full_name")} required><input value={leader.full_name} onChange={(e) => setLeader({ ...leader, full_name: e.target.value })} /></Field>
          <Field label="Institutional e-mail" error={E("leader.email")} required><input type="email" value={leader.email} onChange={(e) => setLeader({ ...leader, email: e.target.value })} /></Field>
          <Field label="Registration number" error={E("leader.registration_number")} required><input placeholder="e.g. RA2311003040001" value={leader.registration_number} onChange={(e) => setLeader({ ...leader, registration_number: e.target.value })} /></Field>
          <Field label="Password" error={E("leader.password")} hint="At least 8 characters, letters and numbers." required><input type="password" autoComplete="new-password" value={leader.password} onChange={(e) => setLeader({ ...leader, password: e.target.value })} /></Field>
          <Field label="Department" hint="Leave blank to use the team department"><input value={leader.department} onChange={(e) => setLeader({ ...leader, department: e.target.value })} /></Field>
          <Field label="Programme" hint="Leave blank to use the team programme"><input value={leader.programme} onChange={(e) => setLeader({ ...leader, programme: e.target.value })} /></Field>
        </div>
        <div className="card-head"><h3>Other members ({total} of {max} max, {min} min including leader)</h3>
          <button type="button" className="btn sm" disabled={total >= max} onClick={() => setMembers([...members, emptyMember()])}><Plus size={14} /> Add member</button></div>
        {members.map((m, i) => (
          <div className="member-card" key={i}>
            <div className="card-head"><b>Member {i + 2}</b><button type="button" className="btn sm" onClick={() => setMembers(members.filter((_, j) => j !== i))} aria-label={`Remove member ${i + 2}`}><Trash2 size={14} /> Remove</button></div>
            <div className="form-grid">
              <Field label="Full name" error={E(`m${i}.full_name`)} required><input value={m.full_name} onChange={(e) => upd(i, "full_name", e.target.value)} /></Field>
              <Field label="Institutional e-mail" error={E(`m${i}.email`)} required><input type="email" value={m.email} onChange={(e) => upd(i, "email", e.target.value)} /></Field>
              <Field label="Registration number" error={E(`m${i}.registration_number`)} required><input placeholder="e.g. RA2311003040001" value={m.registration_number} onChange={(e) => upd(i, "registration_number", e.target.value)} /></Field>
              <Field label="Year / semester"><input value={m.year_semester} onChange={(e) => upd(i, "year_semester", e.target.value)} /></Field>
              <Field label="Department" error={E(`m${i}.department`)} hint="Blank = team department"><input value={m.department} onChange={(e) => upd(i, "department", e.target.value)} /></Field>
              <Field label="Programme" error={E(`m${i}.programme`)} hint="Blank = team programme"><input value={m.programme} onChange={(e) => upd(i, "programme", e.target.value)} /></Field>
            </div>
          </div>))}
        <button className="btn primary" disabled={busy || !meta.active_cycle}>{busy ? "Registering…" : "Register team"}</button>
      </form>
      <p className="small"><Link to="/login">Already registered? Sign in</Link></p>
    </AuthLayout>
  );
}

export function FacultyRegister() {
  const nav = useNavigate();
  const toast = useToast();
  const domains = useDomains();
  const [meta, setMeta] = useState(null);
  const [f, setF] = useState({ full_name: "", email: "", employee_id: "", department: "", designation: "", password: "", additional_interests: "", is_available: true, requested_capacity: 5 });
  const [exp, setExp] = useState([]), [sup, setSup] = useState([]), [int, setInt] = useState([]);
  const [custom, setCustom] = useState("");
  const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => { api("/meta").then(setMeta); }, []);
  const opts = domains.map((d) => ({ value: d.id, label: d.name }));
  const otherId = domains.find((d) => d.is_other)?.id;
  const needsCustom = [exp, sup, int].some((l) => l.includes(otherId));
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const submit = async (e) => {
    e.preventDefault(); setErr("");
    const mailErr = emailError(f.email); if (mailErr) return setErr(mailErr);
    if (!exp.length) return setErr("Select at least one area of expertise.");
    if (needsCustom && custom.trim().length < 3) return setErr("Enter your custom domain name (required when 'Other' is selected).");
    setBusy(true);
    try {
      await api("/register/faculty", { method: "POST", body: { ...f, requested_capacity: Number(f.requested_capacity), expertise_domain_ids: exp, supported_domain_ids: sup, interest_domain_ids: int, custom_domain_name: needsCustom ? custom : null } });
      toast.success("Registration received. An administrator must approve it."); nav("/login");
    } catch (x) { setErr(x.message); } finally { setBusy(false); }
  };
  return (
    <AuthLayout wide>
      <h2>Faculty registration</h2>
      <p className="muted">Your registration stays <b>pending</b> until an administrator approves it. You will not be assigned teams before then.</p>
      {err && <div className="alert error" role="alert">{err}</div>}
      <form onSubmit={submit}>
        <div className="form-grid">
          <Field label="Full name" required><input required value={f.full_name} onChange={set("full_name")} /></Field>
          <Field label="Institutional e-mail" required hint="Must end with @srmist.edu.in"><input type="email" required placeholder="name@srmist.edu.in" value={f.email} onChange={set("email")} /></Field>
          <Field label="Employee ID" required><input required value={f.employee_id} onChange={set("employee_id")} /></Field>
          <Field label="Department" required><input required value={f.department} onChange={set("department")} /></Field>
          <Field label="Designation" required hint="Pick a suggestion or type your own">
            <input required list="desig" value={f.designation} onChange={set("designation")} />
          </Field>
          <datalist id="desig">{(meta?.designations || []).map((d) => <option key={d} value={d} />)}</datalist>
          <Field label="Password" hint="At least 8 characters, letters and numbers." required><input type="password" autoComplete="new-password" required value={f.password} onChange={set("password")} /></Field>
          <Field label="Maximum project capacity (teams)" hint="Number of TEAM projects you can supervise; the administrator confirms the final value."><input type="number" min="1" max="100" value={f.requested_capacity} onChange={set("requested_capacity")} /></Field>
          <Field label="Availability"><select value={String(f.is_available)} onChange={(e) => setF({ ...f, is_available: e.target.value === "true" })}><option value="true">Available</option><option value="false">Not available</option></select></Field>
        </div>
        <MultiSelect label="Areas of expertise *" options={opts} value={exp} onChange={setExp} />
        <MultiSelect label="Supported project domains" options={opts} value={sup} onChange={setSup} hint="Domains you are willing to guide even if not your core expertise." />
        <MultiSelect label="Additional interests (domains)" options={opts} value={int} onChange={setInt} />
        {needsCustom && <Field label="Custom domain name" required hint="Shown because you selected “Other”. It is saved for admin review."><input value={custom} onChange={(e) => setCustom(e.target.value)} /></Field>}
        <Field label="Other interests (free text)"><textarea rows={2} value={f.additional_interests} onChange={set("additional_interests")} /></Field>
        <button className="btn primary" disabled={busy}>{busy ? "Submitting…" : "Submit registration"}</button>
      </form>
      <p className="small"><Link to="/login">Back to sign in</Link></p>
    </AuthLayout>
  );
}
