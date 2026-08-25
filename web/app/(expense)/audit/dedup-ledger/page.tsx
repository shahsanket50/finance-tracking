'use client';

import { useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Badge } from '@/components/ui/badge';
import { Money } from '@/components/money';
import { rowStatus } from '@/lib/audit';
import type { DedupLedgerResponse } from '@/lib/audit';

export default function DedupLedgerPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const from = searchParams.get('from');
  const to = searchParams.get('to');

  const [data, setData] = useState<DedupLedgerResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams();
    if (from) params.set('from', from);
    if (to) params.set('to', to);
    const qs = params.size > 0 ? `?${params.toString()}` : '';

    setLoading(true);
    fetch(`/api/v1/audit/dedup-ledger${qs}`)
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json() as Promise<DedupLedgerResponse>;
      })
      .then((d) => { setData(d); setLoading(false); })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : 'Failed to load');
        setLoading(false);
      });
  }, [from, to]);

  function clearFilter() {
    router.push('/audit/dedup-ledger');
  }

  const isFiltered = Boolean(from || to);

  return (
    <div className="screen">
      <div className="page-head">
        <h2>Dedup ledger</h2>
        <p>Every transaction: seen vs counted, traced to source.</p>
      </div>

      {isFiltered && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
          <span className="card-sub" style={{ margin: 0 }}>
            Filtered: {from} → {to}
          </span>
          <button
            onClick={clearFilter}
            style={{ fontSize: '12px', cursor: 'pointer', background: 'none', border: 'none', color: 'var(--accent)', padding: 0 }}
          >
            ✕ Clear
          </button>
        </div>
      )}

      {loading && <div className="card"><div className="card-sub">Loading…</div></div>}
      {error && <div className="card"><div className="card-sub">Error: {error}</div></div>}

      {data && !loading && (
        <>
          <div className="card" style={{ display: 'flex', gap: '24px' }}>
            <div>
              <div className="card-title">{data.total_seen}</div>
              <div className="card-sub" style={{ margin: 0 }}>Seen</div>
            </div>
            <div>
              <div className="card-title">{data.total_counted}</div>
              <div className="card-sub" style={{ margin: 0 }}>Counted</div>
            </div>
            <div>
              <div className="card-title">{data.total_excluded}</div>
              <div className="card-sub" style={{ margin: 0 }}>Excluded</div>
            </div>
          </div>

          {data.entries.length === 0 && (
            <div className="card">
              <div className="card-sub" style={{ marginBottom: 0 }}>No transactions in this range.</div>
            </div>
          )}

          {data.entries.map((entry) => {
            const status = rowStatus(entry);
            return (
              <div key={entry.idempotency_hash} className="card">
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                  <Money paise={BigInt(entry.amount_paise)} />
                  <Badge variant={status.variant}>{status.label}</Badge>
                </div>
                <div className="card-sub">{entry.value_date} · {entry.account_ref}</div>
                <div className="card-sub" style={{ marginBottom: 0, fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                  {entry.covering_ingestion_event_ids.map((id) => (
                    <span key={id} style={{ marginRight: '8px' }}>↳ {id.slice(0, 8)}…</span>
                  ))}
                </div>
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}
