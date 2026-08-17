/**
 * Independent test-authoring: formatPaise
 *
 * Contract (from TRD §15 / CLAUDE.md §3.5):
 *   formatPaise(paise: bigint): string
 *   - Converts paise (integer, bigint) to ₹-prefixed string
 *   - Indian grouping: rightmost 3 digits, then 2-digit groups leftward
 *   - Always 2 decimal places (the paise portion)
 *   - Negative amounts: minus sign (−, U+2212) before ₹
 *   - Throws TypeError if input is not a bigint
 *   - Never accepts number or float — bigint only
 */
import { describe, it, expect } from 'vitest';
import { formatPaise } from './format';

describe('formatPaise — basic conversions', () => {
  it('formats zero', () => {
    expect(formatPaise(0n)).toBe('₹0.00');
  });

  it('formats 1 paisa', () => {
    expect(formatPaise(1n)).toBe('₹0.01');
  });

  it('formats 50 paise', () => {
    expect(formatPaise(50n)).toBe('₹0.50');
  });

  it('formats 1 rupee (100 paise)', () => {
    expect(formatPaise(100n)).toBe('₹1.00');
  });

  it('formats rupees with paise', () => {
    expect(formatPaise(12350n)).toBe('₹123.50');
  });

  it('formats 999 rupees 99 paise', () => {
    expect(formatPaise(99999n)).toBe('₹999.99');
  });
});

describe('formatPaise — Indian grouping', () => {
  it('formats 1,000 rupees (no lakh separator)', () => {
    expect(formatPaise(100000n)).toBe('₹1,000.00');
  });

  it('formats 10,000 rupees', () => {
    expect(formatPaise(1000000n)).toBe('₹10,000.00');
  });

  it('formats 1,00,000 rupees (1 lakh)', () => {
    expect(formatPaise(10000000n)).toBe('₹1,00,000.00');
  });

  it('formats 10,00,000 rupees (10 lakh)', () => {
    expect(formatPaise(100000000n)).toBe('₹10,00,000.00');
  });

  it('formats 1,00,00,000 rupees (1 crore)', () => {
    expect(formatPaise(1000000000n)).toBe('₹1,00,00,000.00');
  });

  it('formats 12,34,567 rupees 89 paise', () => {
    expect(formatPaise(123456789n)).toBe('₹12,34,567.89');
  });

  it('JSON-bigint round-trip: BigInt(jsonString) produces correct output', () => {
    // CLAUDE.md §3.5: API serializes money as strings. Frontend converts via BigInt(s).
    // This confirms the BigInt(string) → formatPaise path is correct — not just bigint literals.
    const fromJson = BigInt('10000000'); // ₹1,00,000.00 (1 lakh) arriving as JSON string
    expect(formatPaise(fromJson)).toBe('₹1,00,000.00');
  });
});

describe('formatPaise — negative values', () => {
  it('uses minus sign (U+2212) before ₹ for negative amounts', () => {
    const result = formatPaise(-100n);
    expect(result).toBe('\u2212₹1.00');
  });

  it('formats negative with grouping', () => {
    expect(formatPaise(-10000000n)).toBe('\u2212₹1,00,000.00');
  });

  it('negative zero is still zero', () => {
    expect(formatPaise(-0n)).toBe('₹0.00');
  });
});

describe('formatPaise — TypeError for non-bigint inputs', () => {
  it('throws TypeError for a plain number', () => {
    expect(() => formatPaise(100 as unknown as bigint)).toThrow(TypeError);
  });

  it('throws TypeError for a plain integer the size of an API response value (realistic missed-BigInt-conversion)', () => {
    // CLAUDE.md §3.5: API sends money as string; frontend must call BigInt(s) before formatPaise.
    // Passing the raw JSON.parse number is the realistic mistake — it looks like a valid amount.
    expect(() => formatPaise(10000000 as unknown as bigint)).toThrow(TypeError);
  });

  it('throws TypeError for a float', () => {
    expect(() => formatPaise(1.5 as unknown as bigint)).toThrow(TypeError);
  });

  it('throws TypeError for a string', () => {
    expect(() => formatPaise('100' as unknown as bigint)).toThrow(TypeError);
  });

  it('throws TypeError for null', () => {
    expect(() => formatPaise(null as unknown as bigint)).toThrow(TypeError);
  });

  it('throws TypeError for undefined', () => {
    expect(() => formatPaise(undefined as unknown as bigint)).toThrow(TypeError);
  });

  it('TypeError message mentions bigint', () => {
    expect(() => formatPaise(42 as unknown as bigint)).toThrow(/bigint/i);
  });
});
