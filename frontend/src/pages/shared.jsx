import React, { useCallback, useState } from "react";
import { api, fmt } from "../api.js";
import { useAuth } from "../auth.jsx";
import { Card, DataTable, Field, PageHead, useToast } from "../ui.jsx";

export function Notifications({ onChange }) {
  const [k, setK] = useState(0);
  const toast = useToast();
  const load = useCallback((p) => api("/notifications", { params: { page: p.page, page_size: p.page_size } }), []);
  const mark = async (id) => { await api(`/notifications/${id}/read`, { method: "POST" }); setK(k + 1); onChange?.(); };
  const all = async () => { await api("/notifications/read-all", { method: "POST" }); toast.success("All marked as read"); setK(k + 1); onChange?.(); };
  return (
    <>
      <PageHead title="Notifications" actions={<button className="btn" onClick={all}>Mark all as read</button>} />
      <Card>
        <DataTable refreshKey={k} load={load} pageSize={15} empty="You have no notifications yet."
          columns={[
            { key: "title", label: "Notification", render: (n) => <div><b>{n.title}</b>{!n.is_read && <span className="badge warn" style={{ marginLeft: 8 }}>new</span>}<div className="muted small">{n.message}</div></div> },
            { key: "created_at", label: "When", render: (n) => fmt(n.created_at) },
            { key: "a", label: "", render: (n) => !n.is_read && <button className="btn sm" onClick={() => mark(n.id)}>Mark read</button> },
          ]} />
      </Card>
    </>
  );
}

export function Account() {
  const { user } = useAuth();
  const toast = useToast();
  const [f, setF] = useState({ current_password: "", new_password: "" });
  const [err, setErr] = useState("");
  const submit = async (e) => {
    e.preventDefault(); setErr("");
    try {
      const r = await api("/auth/change-password", { method: "POST", body: f });
      sessionStorage.setItem("pga_token", r.access_token);
      toast.success("Password changed"); setF({ current_password: "", new_password: "" });
    } catch (x) { setErr(x.message); }
  };
  return (
    <>
      <PageHead title="Account settings" />
      <div className="grid g2">
        <Card title="Profile"><dl className="kv"><dt>Name</dt><dd>{user.full_name}</dd><dt>E-mail</dt><dd>{user.email}</dd><dt>Role</dt><dd>{user.role.replace("_", " ")}</dd></dl></Card>
        <Card title="Change password">
          {err && <div className="alert error">{err}</div>}
          <form onSubmit={submit}>
            <Field label="Current password"><input type="password" autoComplete="current-password" required value={f.current_password} onChange={(e) => setF({ ...f, current_password: e.target.value })} /></Field>
            <Field label="New password" hint="At least 8 characters with letters and numbers."><input type="password" autoComplete="new-password" required value={f.new_password} onChange={(e) => setF({ ...f, new_password: e.target.value })} /></Field>
            <button className="btn primary">Update password</button>
          </form>
        </Card>
      </div>
    </>
  );
}
