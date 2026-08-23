'use client';

import { useEffect, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import type { SyncHistoryEntry } from '@/lib/audit';

export default function SyncHistoryPage() {
  const [entries, setEntries] = useState<SyncHistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/v1/audit/sync-history')
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json() as Promise<SyncHistoryEntry[]>;
      })
      .then((data) => { setEntries(data); setLoading(false); })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : 'Failed to load');
        setLoading(false);
      });
  }, []);

  return (
    <div className="screen">
      <div className="page-head">
        <h2>Sync history</h2>
        <p>Per-account ingestion progress. PRD §15.1.</p>
      </div>

      {loading && <div className="card"><div className="card-sub">Loading…</div></div>}
      {error && <div className="card"><div className="card-sub">Error: {error}</div></div>}

      {!loading && !error && entries.length === 0 && (
        <div className="card">
          <div className="card-sub" style={{ marginBottom: 0 }}>No statements ingested yet.</div>
        </div>
      )}

      {entries.map((entry) => {
        const stalled = entry.is_stalled;
        return (
          <div key={entry.event_id} className="card">
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
              <div className="card-title" style={{ margin: 0 }}>{entry.account_ref}</div>
              <Badge variant={stalled ? 'warning' : 'default'}>
                {stalled ? 'Stalled' : entry.status}
              </Badge>
            </div>
            <div className="card-sub">
              {entry.bank} · {entry.period_start ?? '?'} → {entry.period_end ?? '?'}
            </div>
            <div className="card-sub" style={{ marginBottom: 0 }}>
              {entry.records_added} added · {entry.records_skipped} skipped
              {entry.confidence !== null && ` · ${(entry.confidence / 100).toFixed(0)}% confidence`}
            </div>
          </div>
        );
      })}
    </div>
  );
}
