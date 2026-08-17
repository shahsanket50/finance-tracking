/** Formats paise as ₹ with Indian grouping. Implements TRD §15 / CLAUDE.md §3.5. */

/**
 * Converts a bigint paise value to a ₹-prefixed display string.
 *
 * Indian grouping: rightmost 3 digits, then 2-digit groups leftward.
 * Negative values: U+2212 MINUS SIGN before ₹.
 * Throws TypeError for any non-bigint input — floats are never accepted.
 */
export function formatPaise(paise: bigint): string {
  if (typeof paise !== 'bigint') {
    throw new TypeError(`formatPaise expects bigint, got ${typeof paise}`);
  }

  const negative = paise < 0n;
  const abs = negative ? -paise : paise;

  const rupees = abs / 100n;
  const cents = abs % 100n;

  const grouped = indianGroup(rupees.toString());
  const paiseStr = cents.toString().padStart(2, '0');

  const body = `₹${grouped}.${paiseStr}`;
  return negative ? `\u2212${body}` : body;
}

/** Applies Indian comma grouping to a non-negative integer string. */
function indianGroup(s: string): string {
  if (s.length <= 3) return s;
  const tail = s.slice(-3);
  const head = s.slice(0, -3);
  const parts: string[] = [];
  for (let i = head.length; i > 0; i -= 2) {
    parts.unshift(head.slice(Math.max(0, i - 2), i));
  }
  return parts.join(',') + ',' + tail;
}
