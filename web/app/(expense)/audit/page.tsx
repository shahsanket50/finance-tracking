import Link from 'next/link';

const SUB_VIEWS = [
  {
    href: '/audit/sync-history',
    title: 'Sync history',
    desc: 'Per-account ingestion progress — how far each statement source has been processed.',
  },
  {
    href: '/audit/overlap-map',
    title: 'Overlap map',
    desc: 'Statement-period overlaps per account — where two uploads cover the same dates.',
  },
  {
    href: '/audit/dedup-ledger',
    title: 'Dedup ledger',
    desc: 'Every transaction: seen vs counted, traced to source, with exclusion reasons.',
  },
  {
    href: '/audit/pairings',
    title: 'Resolver pairings',
    desc: 'What the resolver matched and why — transfers, CC payments, FD bookings, reversals.',
  },
];

export default function AuditPage() {
  return (
    <div className="screen">
      <div className="page-head">
        <h2>Audit</h2>
        <p>Statement coverage, dedup ledger, and resolver pairings. PRD §15.</p>
      </div>

      {SUB_VIEWS.map((v) => (
        <Link key={v.href} href={v.href} style={{ display: 'block', textDecoration: 'none' }}>
          <div className="card" style={{ cursor: 'pointer' }}>
            <div className="card-title">{v.title}</div>
            <div className="card-sub" style={{ marginBottom: 0 }}>{v.desc}</div>
          </div>
        </Link>
      ))}
    </div>
  );
}
