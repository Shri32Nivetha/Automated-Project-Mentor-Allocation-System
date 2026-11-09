import React, { useState } from "react";
import { api, download } from "../api.js";
import { Badge, Card, Empty, PageHead, Spinner, useAsync, useToast } from "../ui.jsx";
import { CycleSelect } from "./common.jsx";

/* Two read-only reports built from live MySQL data; the same payload feeds the screen, PDF and XLSX downloads. */
function Downloads({ path, base, cid, disabled }) {
  const toast = useToast();
  const get = (format, ext) => download(`/admin/reports/${path}`, `${base}.${ext}`, { cycle_id: cid, format }).catch((x) => toast.error(x.message));
  return (<>
    <button className="btn primary" disabled={disabled} onClick={() => get("pdf", "pdf")}>Download PDF</button>
    <button className="btn" disabled={disabled} onClick={() => get("xlsx", "xlsx")}>Download Excel</button>
  </>);
}

export function AdminTeamComposition() {
  const [cid, setCid] = useState(null);
  const { data, loading, error } = useAsync(() => (cid ? api("/admin/reports/team-composition", { params: { cycle_id: cid } }) : Promise.resolve(null)), [cid]);
  return (
    <>
      <PageHead title="Team composition report" sub="All registered teams with their team lead and members (live data from MySQL)."
        actions={<><CycleSelect value={cid} onChange={setCid} /><Downloads path="team-composition" base="team_composition_report" cid={cid} disabled={!cid || !data} /></>} />
      {error && <div className="alert error">{error}</div>}
      {loading || !data ? <Spinner /> : !data.teams.length ? <Card><Empty>No teams are registered in this cycle.</Empty></Card> : (<>
        <p className="muted">Total teams: <b>{data.total_teams}</b> · Total students: <b>{data.total_students}</b></p>
        {data.teams.map((t) => (
          <Card key={t.team_id} title={`Team ID ${t.team_id} — ${t.team_name}`}>
            <div className="row" style={{ marginBottom: 10 }}>
              <span>Team lead: <b>{t.lead_name}</b> ({t.lead_registration_number})</span>
              {!t.complete && <Badge value={t.note} tone="warn" />}
            </div>
            <div className="table-wrap"><table className="report">
              <thead><tr><th>#</th><th>Member name</th><th>Register number</th><th>Role</th></tr></thead>
              <tbody>{t.members.map((m, i) => (
                <tr key={`${t.team_id}-${m.registration_number}`} style={m.is_leader ? { fontWeight: 600 } : undefined}>
                  <td>{i + 1}</td><td>{m.name}</td><td>{m.registration_number}</td><td>{m.is_leader ? <Badge value="Team Lead" tone="ok" /> : "Member"}</td>
                </tr>))}</tbody>
            </table></div>
          </Card>))}
      </>)}
    </>
  );
}

export function AdminTeamMentor() {
  const [cid, setCid] = useState(null);
  const { data, loading, error } = useAsync(() => (cid ? api("/admin/reports/team-mentor", { params: { cycle_id: cid } }) : Promise.resolve(null)), [cid]);
  return (
    <>
      <PageHead title="Team–mentor allocation report" sub="One row per team with its assigned mentor (live data from MySQL)."
        actions={<><CycleSelect value={cid} onChange={setCid} /><Downloads path="team-mentor" base="team_mentor_allocation_report" cid={cid} disabled={!cid || !data} /></>} />
      {error && <div className="alert error">{error}</div>}
      <Card>{loading || !data ? <Spinner /> : !data.rows.length ? <Empty>No teams are registered in this cycle.</Empty> : (<>
        <p className="muted" style={{ marginTop: 0 }}>Total teams: <b>{data.total_teams}</b> · Mentor assigned: <b>{data.assigned_teams}</b> · Not assigned: <b>{data.total_teams - data.assigned_teams}</b></p>
        <div className="table-wrap"><table className="report">
          <thead><tr><th>Team ID</th><th>Team name</th><th>Team lead</th><th>Mentor name</th><th>Mentor ID</th><th>Mentor email</th></tr></thead>
          <tbody>{data.rows.map((r) => (
            <tr key={r.team_id}><td>{r.team_id}</td><td>{r.team_name}</td><td>{r.lead_name}</td>
              <td>{r.assigned ? r.mentor_name : <Badge value="Not Assigned" tone="warn" />}</td><td>{r.mentor_id}</td><td>{r.mentor_email}</td></tr>))}</tbody>
        </table></div></>)}</Card>
    </>
  );
}
