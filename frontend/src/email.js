// Institutional e-mail rule: registrations must use exactly @srmist.edu.in (any username).
// Mirrors backend/app/services/common.py::check_institutional_email (the backend remains the authority).
export const INSTITUTIONAL_DOMAIN = "srmist.edu.in";
export const normEmail = (v) => String(v || "").trim().toLowerCase();
export const emailError = (v) => {
  const e = normEmail(v);
  if (!/^\S+@\S+\.\S+$/.test(e)) return "Enter a valid e-mail address";
  return e.slice(e.lastIndexOf("@") + 1) === INSTITUTIONAL_DOMAIN ? null : `Use your institutional e-mail ending in @${INSTITUTIONAL_DOMAIN}`;
};
