/** Renders a paise amount with IBM Plex Mono font. Implements TRD §15.3. */
import { formatPaise } from "../lib/format";

interface MoneyProps {
  paise: bigint;
  className?: string;
}

/**
 * Display component for monetary amounts. Takes paise (bigint) only —
 * the component never stores or derives a formatted string; it renders on demand.
 */
export function Money({ paise, className = "" }: MoneyProps) {
  return (
    <span
      className={`font-mono tabular-nums ${className}`}
      style={{ fontFamily: "var(--font-mono)" }}
    >
      {formatPaise(paise)}
    </span>
  );
}
