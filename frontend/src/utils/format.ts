/**
 * Format integer paise as Indian rupee display string.
 * e.g. 14213400 → "₹1,42,134"
 * Display only — never used for financial computations.
 */
export function formatPaise(paise: number): string {
  const rupees = Math.floor(paise / 100);
  return '₹' + rupees.toLocaleString('en-IN');
}

/**
 * Format basis points as percentage string.
 * e.g. 5231 → "52.31%"
 */
export function formatBps(bps: number): string {
  const whole = Math.floor(bps / 100);
  const frac = bps % 100;
  return `${whole}.${frac.toString().padStart(2, '0')}%`;
}

/**
 * Format confidence score (0.0–1.0) as percentage.
 * e.g. 0.87 → "87%"
 */
export function formatConfidence(score: number): string {
  return `${Math.round(score * 100)}%`;
}

/**
 * Strip synthetic ground-truth prefix from failure_description.
 * Backend inserts [recoverable] / [unrecovered] / [self_healed] for test harness.
 * We strip it before displaying to users.
 */
export function cleanDescription(desc: string | null | undefined): string {
  if (!desc) return '—';
  return desc.replace(/^\[(recoverable|unrecovered|self_healed)\]\s*/i, '');
}
