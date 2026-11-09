// Register number format: RA + 2-digit batch + fixed code 11003040 + 3-digit student number (001-999).
// Mirrors backend/app/services/common.py (the backend remains the authority).
export const REGNO_RE = /^RA\d{2}11003040(?!000)\d{3}$/;
export const REGNO_MESSAGE = "Invalid register number. Use the format RA{BATCH}11003040{NNN}";
export const normRegno = (v) => String(v || "").replace(/\s+/g, "").toUpperCase();
export const regnoError = (v) => (REGNO_RE.test(normRegno(v)) ? null : REGNO_MESSAGE);
