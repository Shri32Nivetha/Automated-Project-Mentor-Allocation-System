import React, { useEffect } from "react";
import { api } from "../api.js";
import { useAsync } from "../ui.jsx";

export function CycleSelect({ value, onChange }) {
  const { data } = useAsync(() => api("/admin/cycles"), []);
  useEffect(() => { if (data && !value) { const a = data.find((c) => c.is_active) || data[0]; if (a) onChange(a.id); } }, [data]);
  if (!data) return null;
  return <select aria-label="Allocation cycle" value={value || ""} onChange={(e) => onChange(Number(e.target.value))} style={{ width: "auto" }}>{data.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.status}{c.is_active ? ", current" : ""})</option>)}</select>;
}
export const NoCycle = () => <div className="alert warn">No allocation cycle exists yet. Create and activate one under <b>Academic cycles</b>.</div>;
