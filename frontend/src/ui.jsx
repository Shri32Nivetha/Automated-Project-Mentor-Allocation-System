import React, { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from "react";
import { CheckCircle2, AlertCircle, AlertTriangle, Info, X, Search, ChevronLeft, ChevronRight, ArrowUpDown, Inbox } from "lucide-react";
import { api } from "./api.js";

/* ---------- toasts ---------- */
const ToastCtx = createContext(null);
export const useToast = () => useContext(ToastCtx);
export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const push = useCallback((message, type = "success") => {
    const id = Math.random();
    setItems((s) => [...s, { id, message, type }]);
    setTimeout(() => setItems((s) => s.filter((i) => i.id !== id)), 6000);
  }, []);
  const toast = useRef({ success: (m) => push(m, "success"), error: (m) => push(m, "error") }).current;
  return (
    <ToastCtx.Provider value={toast}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.type}`}>
            {t.type === "success" ? <CheckCircle2 size={18} aria-hidden /> : <AlertCircle size={18} aria-hidden />}
            <span>{t.type === "error" ? <span className="sr-only">Error: </span> : null}{t.message}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

/* ---------- small primitives ---------- */
export function Alert({ tone = "info", title, children, strong }) {
  const Icon = { error: AlertCircle, warn: AlertTriangle, ok: CheckCircle2, info: Info }[tone];
  return (
    <div className={`alert ${tone} ${strong ? "strong" : ""}`} role={tone === "error" || tone === "warn" ? "alert" : "status"}>
      <Icon size={18} aria-hidden />
      <div className="body">{title && <b>{title} </b>}{children}</div>
    </div>
  );
}
export const Btn = ({ busy, children, className = "", ...p }) => (
  <button className={`btn ${className}`} disabled={busy || p.disabled} {...p}>{busy && <span className="spin" aria-hidden />}{children}</button>
);
export function Tip({ text, children }) {
  const id = useId();
  return <span className="tip">{React.cloneElement(children, { "aria-describedby": id })}<span role="tooltip" id={id}>{text}</span></span>;
}

/* ---------- modal + confirm ---------- */
const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
export function Modal({ title, onClose, children, wide, size, footer, dismissible = true }) {
  const ref = useRef();
  const closeRef = useRef(onClose);
  closeRef.current = onClose;                       // latest handler without re-running the focus effect
  useEffect(() => {
    const prev = document.activeElement;
    const first = ref.current?.querySelector("[data-autofocus]") || ref.current;
    first?.focus();
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const key = (e) => {
      if (e.key === "Escape" && dismissible) { e.stopPropagation(); closeRef.current(); }
      if (e.key === "Tab" && ref.current) {         // keep keyboard focus inside the dialog
        const els = [...ref.current.querySelectorAll(FOCUSABLE)];
        if (!els.length) return;
        const a = els[0], z = els[els.length - 1];
        if (e.shiftKey && (document.activeElement === a || document.activeElement === ref.current)) { e.preventDefault(); z.focus(); }
        else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
      }
    };
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("keydown", key); document.body.style.overflow = prevOverflow; prev?.focus?.(); };
  }, [dismissible]);
  const cls = size || (wide ? "wide" : "");
  return (
    <div className="overlay" onMouseDown={(e) => dismissible && e.target === e.currentTarget && onClose()}>
      <div className={`modal ${cls}`} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={ref}>
        <div className="modal-head"><h3>{title}</h3><button className="icon-btn" onClick={onClose} aria-label="Close dialog"><X size={18} /></button></div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

const ConfirmCtx = createContext(null);
export const useConfirm = () => useContext(ConfirmCtx);
export function ConfirmProvider({ children }) {
  const [state, setState] = useState(null);
  const [reason, setReason] = useState("");
  const confirm = useCallback((opts) => new Promise((resolve) => { setReason(""); setState({ ...opts, resolve }); }), []);
  const close = (v) => { state.resolve(v); setState(null); };
  return (
    <ConfirmCtx.Provider value={confirm}>
      {children}
      {state && (
        <Modal title={state.title || "Please confirm"} onClose={() => close(null)}
          footer={<>
            <button className="btn" onClick={() => close(null)}>Cancel</button>
            <button className={`btn ${state.danger ? "danger" : "primary"}`}
              disabled={state.reasonRequired && reason.trim().length < 3}
              onClick={() => close(state.reasonRequired ? { reason: reason.trim() } : true)}>{state.confirmLabel || "Confirm"}</button>
          </>}>
          <div style={{ whiteSpace: "pre-line" }}>{state.message}</div>
          {state.reasonRequired && (
            <div style={{ marginTop: 14 }}><Field label={state.reasonLabel || "Reason"} required hint="At least 3 characters.">
              <textarea data-autofocus value={reason} onChange={(e) => setReason(e.target.value)} rows={3} />
            </Field></div>
          )}
        </Modal>
      )}
    </ConfirmCtx.Provider>
  );
}

/* ---------- form bits ---------- */
export function Field({ label, error, hint, children, required }) {
  const id = useId();
  const child = React.isValidElement(children) && typeof children.type === "string"
    ? React.cloneElement(children, { id, "aria-invalid": !!error || undefined, "aria-required": required || undefined, "aria-describedby": error ? id + "e" : hint ? id + "h" : undefined })
    : React.isValidElement(children) && children.type === NumberInput
      ? React.cloneElement(children, { id, "aria-invalid": !!error || undefined, "aria-describedby": error ? id + "e" : hint ? id + "h" : undefined })
      : children;
  return (
    <div className={`field ${error ? "has-error" : ""}`}>
      <label htmlFor={id}>{label}{required && <span className="req" aria-hidden> *</span>}</label>
      {child}
      {hint && !error && <div className="hint" id={id + "h"}>{hint}</div>}
      {error && <div className="err" id={id + "e"} role="alert"><AlertCircle size={14} aria-hidden style={{ marginTop: 2, flexShrink: 0 }} />{error}</div>}
    </div>
  );
}

/* Whole-number input. Real <input type="number">; the browser keeps arrows/keyboard behaviour, validation is repeated in JS
   (and on the server) because type="number" alone still lets "2.5", "-1" or an out-of-range value through. */
export const NumberInput = React.forwardRef(function NumberInput({ value, onChange, min, max, placeholder, ...rest }, ref) {
  return (
    <input ref={ref} type="number" inputMode="numeric" step={1} min={min} max={max} placeholder={placeholder}
      value={value} onChange={(e) => onChange(e.target.value, e.target.validity.badInput)} {...rest} />
  );
});

/* Mirrors services.workload.validate_capacity on the server. Returns "" when valid. */
export function validateWholeNumber(raw, { min, max, badInput = false, what = "Capacity" }) {
  if (badInput) return `${what} must be a whole number (no text).`;
  const s = String(raw ?? "").trim();
  if (s === "") return "Enter the maximum number of projects this faculty member can supervise.";
  if (!/^-?\d+$/.test(s)) return `${what} must be a whole number (no decimals or text).`;
  const n = Number(s);
  if (n < min) return min > 0 ? `${what} must be at least ${min}.` : `${what} cannot be negative.`;
  if (n > max) return `${what} cannot be more than ${max}.`;
  return "";
}

const BADGE = { approved: "ok", allocated: "ok", finalised: "ok", active: "ok", available: "ok", pending: "warn", submitted: "warn",
  under_review: "warn", needs_revision: "warn", draft: "muted", rejected: "bad", planned: "muted", archived: "muted", inactive: "bad",
  unavailable: "warn", "over capacity": "bad", current: "ok" };
export function Badge({ value, tone }) {
  const t = tone || BADGE[value] || "muted";
  return <span className={`badge ${t}`}>{String(value ?? "—").replace(/_/g, " ")}</span>;
}
const TIER_HELP = { primary: "The mentor's expertise or supported domains include the team's primary domain.",
  additional: "No primary match; the mentor matches one or more of the team's additional domains.",
  related: "No exact match; a team domain is the parent or child of one of the mentor's domains.",
  override: "Administrator override: the mentor has no compatible domain.", none: "No compatible domain." };
export function TierBadge({ tier }) {
  const t = tier || "none";
  return <Tip text={TIER_HELP[t]}><span className={`badge tier-${t}`} tabIndex={0}>{t === "none" ? "no match" : t === "override" ? "override" : `${t} match`}</span></Tip>;
}

/* load ÷ capacity bar. Over capacity is shown with colour AND text ("+2 over") so it never relies on colour alone. */
export function UtilBar({ assigned, capacity, projected }) {
  const shown = projected ?? assigned;
  const pct = capacity > 0 ? Math.min(100, (shown / capacity) * 100) : shown > 0 ? 100 : 0;
  const over = Math.max(0, shown - capacity);
  const tone = over > 0 ? "over" : capacity > 0 && shown / capacity >= 0.85 ? "warn" : "";
  return (
    <div className="util" title={`${shown} of ${capacity} project(s)`}>
      <div className={`bar ${tone}`} role="img" aria-label={`${shown} of ${capacity} projects${over ? `, ${over} over capacity` : ""}`}><div style={{ width: `${pct}%` }} /></div>
      <span className="num">{projected !== undefined && projected !== assigned ? `${assigned}→${projected}` : shown} / {capacity}{over > 0 && <b style={{ color: "var(--bad)" }}> +{over} over</b>}</span>
    </div>
  );
}

export const Spinner = ({ label = "Loading…" }) => <div className="spinner" role="status"><span />{label}</div>;
export const Empty = ({ children, title, icon: Icon = Inbox }) => <div className="empty"><span className="empty-ico"><Icon size={20} aria-hidden /></span>{title && <b>{title}</b>}<div>{children}</div></div>;
export const Skeleton = ({ cards = 0, lines = 0 }) => (
  <div aria-busy="true" aria-label="Loading">
    {cards > 0 && <div className="stats">{Array.from({ length: cards }, (_, i) => <div key={i} className="skel skel-card" />)}</div>}
    {Array.from({ length: lines }, (_, i) => <div key={i} className="skel" style={{ height: 16, margin: "12px 0", width: `${90 - (i % 3) * 18}%` }} />)}
  </div>
);
export const Card = ({ title, actions, children, className = "" }) => (
  <section className={`card ${className}`}>{(title || actions) && <div className="card-head"><h3>{title}</h3><div className="row">{actions}</div></div>}{children}</section>
);
export const Stat = ({ label, value, tone, sub, icon: Icon }) => (
  <div className={`stat ${tone || ""}`}>
    <div className="stat-top"><div className="stat-l">{label}</div>{Icon && <span className="stat-ico"><Icon size={17} aria-hidden /></span>}</div>
    <div className="stat-v">{value ?? "—"}</div>{sub && <div className="stat-s">{sub}</div>}
  </div>
);
export const PageHead = ({ title, sub, actions }) => (
  <div className="page-head"><div><h1>{title}</h1>{sub && <p className="muted">{sub}</p>}</div><div className="row">{actions}</div></div>
);

/* ---------- domain catalogue (from MySQL via the API; cached) ---------- */
let domainCache = null;
export function useDomains() {
  const [domains, setDomains] = useState(domainCache || []);
  useEffect(() => { if (!domainCache) api("/domains").then((d) => { domainCache = d; setDomains(d); }); }, []);
  return domains;
}
export const resetDomainCache = () => { domainCache = null; };

export function MultiSelect({ label, options, value, onChange, error, hint, max }) {
  const [q, setQ] = useState("");
  const shown = options.filter((o) => o.label.toLowerCase().includes(q.toLowerCase()));
  const toggle = (id) => {
    if (value.includes(id)) onChange(value.filter((v) => v !== id));
    else if (!max || value.length < max) onChange([...value, id]);
  };
  const name = (id) => options.find((o) => o.value === id)?.label;
  return (
    <Field label={label} error={error} hint={hint}>
      <div className="multi">
        <div className="chips">
          {value.map((v) => <button type="button" className="chip" key={v} onClick={() => toggle(v)} aria-label={`Remove ${name(v)}`}>{name(v)} <X size={12} /></button>)}
          {!value.length && <span className="muted small">None selected</span>}
        </div>
        <input type="search" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} aria-label={`Search ${label}`} />
        <div className="multi-list" role="group" aria-label={label}>
          {shown.map((o) => (
            <label key={o.value} className="check"><input type="checkbox" checked={value.includes(o.value)} onChange={() => toggle(o.value)} />{o.label}</label>
          ))}
          {!shown.length && <div className="muted small pad">No matches</div>}
        </div>
      </div>
    </Field>
  );
}

/* ---------- server-side data table: search, sort, filters, pagination ---------- */
export function DataTable({ columns, load, filters = [], searchPlaceholder = "Search…", refreshKey, onRow, pageSize = 15, empty = "Nothing to show.", rowClass, initialSort = "" }) {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState(initialSort);
  const [fv, setFv] = useState({});
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState("");
  useEffect(() => { const t = setTimeout(() => { setQ(search); setPage(1); }, 300); return () => clearTimeout(t); }, [search]);
  useEffect(() => {
    let live = true;
    setBusy(true);
    load({ page, page_size: pageSize, search: q || undefined, sort: sort || undefined, ...fv })
      .then((r) => { if (live) { setRows(r.items); setTotal(r.total); setErr(""); } })
      .catch((e) => live && setErr(e.message)).finally(() => live && setBusy(false));
    return () => { live = false; };
  }, [page, q, sort, fv, refreshKey, load, pageSize]);
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const toggleSort = (k) => setSort(sort === k ? "-" + k : k);
  const filtered = !!(q || Object.values(fv).some(Boolean));
  return (
    <div>
      <div className="toolbar" role="search">
        <div className="search"><Search size={16} aria-hidden /><input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder={searchPlaceholder} aria-label="Search" /></div>
        {filters.map((f) => (
          <select key={f.key} aria-label={f.label} value={fv[f.key] ?? ""} onChange={(e) => { setFv({ ...fv, [f.key]: e.target.value || undefined }); setPage(1); }}>
            <option value="">{f.label}: all</option>
            {f.options.map((o) => <option key={o.value ?? o} value={o.value ?? o}>{o.label ?? String(o).replace(/_/g, " ")}</option>)}
          </select>
        ))}
        {filtered && <button className="btn ghost sm" onClick={() => { setSearch(""); setFv({}); }}><X size={14} aria-hidden /> Clear filters</button>}
      </div>
      {err && <Alert tone="error">{err}</Alert>}
      <div className="table-wrap" aria-busy={busy}>
        <table className="stack">
          <thead><tr>{columns.map((c) => (
            <th key={c.key} scope="col" aria-sort={sort === c.sort ? "ascending" : sort === "-" + c.sort ? "descending" : undefined}>
              {c.sort ? <button className="th-btn" onClick={() => toggleSort(c.sort)}>{c.label}<ArrowUpDown size={12} aria-hidden /></button> : c.label}
            </th>))}</tr></thead>
          <tbody>
            {busy && !rows.length ? Array.from({ length: 4 }, (_, i) => <tr key={i}><td colSpan={columns.length}><div className="skel" style={{ height: 18 }} /></td></tr>) :
              !rows.length ? <tr><td colSpan={columns.length}><Empty title={filtered ? "No matching results" : undefined}>{filtered ? "Try different search terms or clear the filters." : empty}</Empty></td></tr> :
                rows.map((r, i) => (
                  <tr key={r.id ?? i} className={`${onRow ? "clickable" : ""} ${rowClass?.(r) || ""}`} onClick={() => onRow?.(r)}
                    tabIndex={onRow ? 0 : undefined} onKeyDown={(e) => onRow && (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onRow(r))}>
                    {columns.map((c) => <td key={c.key} data-label={c.label}>{c.render ? c.render(r) : r[c.key] ?? "—"}</td>)}
                  </tr>))}
          </tbody>
        </table>
      </div>
      <div className="pager">
        <span className="muted small" aria-live="polite">{total} result{total === 1 ? "" : "s"}</span>
        <div className="row">
          <button className="icon-btn" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page"><ChevronLeft size={18} /></button>
          <span className="small">Page {page} of {pages}</span>
          <button className="icon-btn" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label="Next page"><ChevronRight size={18} /></button>
        </div>
      </div>
    </div>
  );
}

export function useAsync(fn, deps) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true);
    fn().then((d) => live && (setData(d), setError(""))).catch((e) => live && setError(e.message)).finally(() => live && setLoading(false));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, loading, reload: () => setTick((t) => t + 1) };
}
