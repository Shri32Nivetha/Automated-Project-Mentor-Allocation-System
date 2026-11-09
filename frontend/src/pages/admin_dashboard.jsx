import React, { useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, ArrowRight, CheckCircle2, UsersRound, ShieldAlert, UserCheck, Gauge, Clock } from "lucide-react";
import { api, fmt } from "../api.js";
import { Alert, Badge, Card, Empty, PageHead, Skeleton, Stat, UtilBar, useAsync } from "../ui.jsx";
import { CycleSelect, NoCycle } from "./common.jsx";

const ACTION_LABEL = { auto_assign: "Auto-assigned", auto_reassign: "Re-optimised", manual_assign: "Manually assigned", reassign: "Reassigned",
  unassign: "Guide removed", finalise: "Finalised" };

export function AdminDashboard() {
  const [cid, setCid] = useState(null);
  const { data: d, loading, error } = useAsync(() => api("/admin/dashboard", { params: { cycle_id: cid } }), [cid]);
  if (error) return <><PageHead title="Dashboard" /><Alert tone="error">{error}</Alert><NoCycle /></>;

  // "needs attention" items are derived from real figures only
  const todo = d ? [
    d.pending_faculty_approvals > 0 && { to: "/admin/faculty", tone: "warn", text: `${d.pending_faculty_approvals} faculty registration(s) await approval`, cta: "Review" },
    d.pending_reviews > 0 && { to: "/admin/proposals", tone: "warn", text: `${d.pending_reviews} proposal(s) await review`, cta: "Review" },
    d.teams_requiring_resolution > 0 && { to: "/admin/allocation", tone: "bad", text: `${d.teams_requiring_resolution} team(s) have no compatible mentor and need an administrator decision`, cta: "Resolve" },
    d.overloaded_faculty > 0 && { to: "/admin/workload", tone: "bad", text: `${d.overloaded_faculty} faculty member(s) are above capacity (+${d.total_overload} team(s) in total)`, cta: "Inspect" },
    d.capacity_shortage > 0 && { to: "/admin/workload", tone: "warn", text: `Capacity shortage of ${d.capacity_shortage}: the optimiser will spread unavoidable overload`, cta: "Plan" },
  ].filter(Boolean) : [];
  const pct = d && d.total_teams ? Math.round((d.allocated_teams / d.total_teams) * 100) : 0;
  const workload = d ? [...d.faculty_workload].sort((a, b) => (b.assigned / Math.max(1, b.capacity)) - (a.assigned / Math.max(1, a.capacity))) : [];

  return (
    <>
      <PageHead title="Dashboard" sub={d ? `${d.cycle.name} · cycle ${d.cycle.status}. Live figures for allocation decisions.` : "Loading the current cycle…"}
        actions={<CycleSelect value={cid} onChange={setCid} />} />
      {loading || !d ? <Skeleton cards={7} lines={5} /> : (
        <>
          <div className="stats">
            <Stat label="Total teams" icon={UsersRound} value={d.total_teams} sub={`${d.approved_teams} with approved proposals`} />
            <Stat label="Allocated teams" icon={CheckCircle2} value={d.allocated_teams} tone="ok" sub={`${pct}% of all teams`} />
            <Stat label="Requiring resolution" icon={ShieldAlert} value={d.teams_requiring_resolution} tone={d.teams_requiring_resolution ? "bad" : "ok"} sub="no compatible mentor" />
            <Stat label="Approved faculty" icon={UserCheck} value={d.approved_faculty} sub={`${d.eligible_faculty} eligible now`} />
            <Stat label="Available capacity" icon={Gauge} value={d.remaining_capacity} tone={d.capacity_shortage ? "warn" : ""} sub={`of ${d.total_capacity} team projects`} />
            <Stat label="Faculty overloaded" icon={AlertTriangle} value={d.overloaded_faculty} tone={d.overloaded_faculty ? "bad" : "ok"} sub={d.total_overload ? `+${d.total_overload} above capacity` : "all within capacity"} />
            <Stat label="Pending faculty approvals" icon={Clock} value={d.pending_faculty_approvals} tone={d.pending_faculty_approvals ? "warn" : ""} />
          </div>

          <Card title="Needs your attention">
            {todo.length ? todo.map((t) => (
              <div className="notif" key={t.text}>
                <span className="row"><AlertTriangle size={16} aria-hidden style={{ color: t.tone === "bad" ? "var(--bad)" : "var(--warn)" }} />{t.text}</span>
                <Link className="btn sm" to={t.to}>{t.cta}<ArrowRight size={13} aria-hidden /></Link>
              </div>)) : <div className="row"><CheckCircle2 size={18} aria-hidden style={{ color: "var(--ok)" }} />Nothing needs attention right now.</div>}
          </Card>

          <div className="grid g2">
            <Card title="Faculty workload" actions={<Link className="btn sm ghost" to="/admin/workload">Manage <ArrowRight size={13} aria-hidden /></Link>}>
              {workload.length ? workload.slice(0, 12).map((f) => (
                <div key={f.id} style={{ marginBottom: 12 }}>
                  <div className="row between"><span className="small"><b>{f.name}</b></span></div>
                  <UtilBar assigned={f.assigned} capacity={f.capacity} />
                </div>)) : <Empty title="No approved faculty yet">Approve faculty registrations to start allocating.</Empty>}
              {workload.length > 12 && <p className="small muted">Showing the 12 most utilised of {workload.length}.</p>}
            </Card>
            <Card title="Recent allocation activity" actions={<Link className="btn sm ghost" to="/admin/history">History <ArrowRight size={13} aria-hidden /></Link>}>
              {d.recent_allocation_activity.length ? d.recent_allocation_activity.map((a) => (
                <div className="notif" key={a.id}>
                  <div>
                    <b>{a.team}</b> <span className="small muted">· {ACTION_LABEL[a.action] || a.action}</span>
                    <div className="small muted">{a.old_faculty ? `${a.old_faculty} → ` : ""}{a.new_faculty || "—"}</div>
                    <div className="row" style={{ gap: 4 }}>
                      {a.domain_violation && <Badge value="domain override" tone="bad" />}
                      {a.capacity_violation && <Badge value="over capacity" tone="warn" />}
                    </div>
                  </div>
                  <span className="small muted nowrap">{fmt(a.created_at)}</span>
                </div>)) : <Empty title="No allocation activity yet">Run an allocation preview to get started.</Empty>}
            </Card>
            <Card title="Proposal pipeline">
              {Object.keys(d.proposal_status_counts).length ? (
                <dl className="kv">{Object.entries(d.proposal_status_counts).map(([k, v]) => [<dt key={k}>{k.replace("_", " ")}</dt>, <dd key={k + "v"}><b>{v}</b></dd>])}</dl>
              ) : <Empty>No proposals yet.</Empty>}
            </Card>
            <Card title="Teams by primary domain">
              {d.domain_team_counts.length ? <div className="table-wrap"><table><tbody>{d.domain_team_counts.map((x) => <tr key={x.domain}><td>{x.domain}</td><td style={{ textAlign: "right" }}><b>{x.teams}</b></td></tr>)}</tbody></table></div> : <Empty>No domains chosen yet.</Empty>}
            </Card>
          </div>
        </>)}
    </>
  );
}
