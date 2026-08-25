'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Badge } from '@/components/ui/badge';
import type { AccountOverlap, OverlapMapResponse } from '@/lib/audit';

export default function OverlapMapPage() {
  const [data, setData] = useState<OverlapMapResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    fetch('/api/v1/audit/overlap-map')
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json() as Promise<OverlapMapResponse>;
      })
      .then((d) => { setData(d); setLoading(false); })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : 'Failed to load');
        setLoading(false);
      });
  }, []);

  function handleBarClick(bar: AccountOverlap['statements'][number]) {
    if (bar.overlaps_with.length === 0 || !bar.period_start || !bar.period_end) return;
    const params = new URLSearchParams({ from: bar.period_start, to: bar.period_end });
    router.push(`/audit/dedup-ledger?${params.toString()}`);
  }

  return (
    <div className="screen">
      <div className="page-head">
        <h2>Overlap map</h2>
        <p>Statement-period overlaps per account.</p>
      </div>

      {loading && <div className="card"><div className="card-sub">Loading…</div></div>}
      {error && <div className="card"><div className="card-sub">Error: {error}</div></div>}

      {!loading && !error && data?.accounts.length === 0 && (
        <div className="card">
          <div className="card-sub" style={{ marginBottom: 0 }}>No statements uploaded yet.</div>
        </div>
      )}

      {data?.accounts.map((account) => (
        <div key={account.account_ref} className="card">
          <div className="card-title">{account.account_ref}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {account.statements.map((bar) => {
              const overlapping = bar.overlaps_with.length > 0;
              return (
                <div
                  key={bar.event_id}
                  onClick={() => handleBarClick(bar)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    cursor: overlapping ? 'pointer' : 'default',
                    padding: '4px 0',
                  }}
                >
                  <span className="card-sub" style={{ margin: 0, flex: 1 }}>
                    {bar.period_start ?? '?'} → {bar.period_end ?? '?'}
                  </span>
                  {overlapping && (
                    <Badge variant="warning">Overlap</Badge>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
