'use client';

import { useEffect, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Money } from '@/components/money';
import { pairingLabel, confidencePct } from '@/lib/audit';
import type { ResolverPairing, AccountTransaction } from '@/lib/audit';

const MARKED_CC_PAYMENT = 'MarkedCCPayment';

function CCDrillDown({ leg }: { leg: ResolverPairing['legs'][number] }) {
  const [txns, setTxns] = useState<AccountTransaction[] | null>(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  function toggle() {
    if (!open && txns === null) {
      setLoading(true);
      const params = new URLSearchParams();
      if (leg.period_start) params.set('from', leg.period_start);
      if (leg.period_end) params.set('to', leg.period_end);
      fetch(`/api/v1/accounts/${encodeURIComponent(leg.account_ref)}/transactions?${params.toString()}`)
        .then((r) => r.json() as Promise<AccountTransaction[]>)
        .then((data) => { setTxns(data); setLoading(false); })
        .catch(() => { setTxns([]); setLoading(false); });
    }
    setOpen((v) => !v);
  }

  return (
    <div style={{ marginTop: '8px' }}>
      <button
        onClick={toggle}
        style={{ fontSize: '12px', cursor: 'pointer', background: 'none', border: 'none', color: 'var(--accent)', padding: 0 }}
      >
        {open ? '▲ Hide purchases' : '▼ Show purchases in billing period'}
      </button>
      {open && (
        <div style={{ marginTop: '8px', paddingLeft: '12px' }}>
          {loading && <div className="card-sub">Loading…</div>}
          {txns?.length === 0 && <div className="card-sub">No transactions in billing period.</div>}
          {txns?.map((t) => (
            <div key={t.idempotency_hash} style={{ display: 'flex', gap: '8px', padding: '4px 0' }}>
              <span className="card-sub" style={{ margin: 0 }}>{t.value_date}</span>
              <Money paise={BigInt(t.amount_paise)} />
              <span className="card-sub" style={{ margin: 0 }}>{t.narration}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function PairingsPage() {
  const [pairings, setPairings] = useState<ResolverPairing[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/v1/audit/resolver-pairings')
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json() as Promise<ResolverPairing[]>;
      })
      .then((data) => { setPairings(data); setLoading(false); })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : 'Failed to load');
        setLoading(false);
      });
  }, []);

  return (
    <div className="screen">
      <div className="page-head">
        <h2>Resolver pairings</h2>
        <p>What the resolver matched and why. PRD §15.3.</p>
      </div>

      {loading && <div className="card"><div className="card-sub">Loading…</div></div>}
      {error && <div className="card"><div className="card-sub">Error: {error}</div></div>}

      {!loading && !error && pairings.length === 0 && (
        <div className="card">
          <div className="card-sub" style={{ marginBottom: 0 }}>No resolver pairings yet.</div>
        </div>
      )}

      {pairings.map((pairing) => {
        // Only show drill-down when the cc_credit leg has a resolved account_ref and
        // a statement period — both are required to fetch the billing-period transactions.
        // If the join missed (leg not yet ingested), account_ref is "" and period is null.
        const rawCcLeg = pairing.event_type === MARKED_CC_PAYMENT
          ? pairing.legs.find((l) => l.role === 'cc_credit')
          : null;
        const ccLeg = (rawCcLeg?.account_ref && rawCcLeg.period_start && rawCcLeg.period_end)
          ? rawCcLeg
          : null;

        return (
          <div key={pairing.event_id} className="card">
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
              <Badge variant="default">{pairingLabel(pairing.event_type)}</Badge>
              <span className="card-sub" style={{ margin: 0 }}>{confidencePct(pairing.confidence)}</span>
              <span className="card-sub" style={{ margin: 0 }}>{pairing.value_date}</span>
            </div>
            <div className="card-sub" style={{ marginBottom: 0 }}>
              {pairing.legs.map((leg) => (
                <div key={leg.idempotency_hash}>
                  {leg.role}: {leg.account_ref} ({leg.period_start ?? '?'} → {leg.period_end ?? '?'})
                </div>
              ))}
            </div>
            {ccLeg && <CCDrillDown leg={ccLeg} />}
          </div>
        );
      })}
    </div>
  );
}
