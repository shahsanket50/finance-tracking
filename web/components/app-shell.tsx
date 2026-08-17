'use client';

import { useState } from 'react';
import { usePathname } from 'next/navigation';
import { Sidebar } from './sidebar';

export type AppContext = 'expense' | 'ca';

const CA_PREFIXES = [
  '/tax-health', '/fy-checklist', '/advance-tax',
  '/deductions', '/capital-gains', '/income-tds', '/documents',
];

function contextFromPath(path: string): AppContext {
  return CA_PREFIXES.some(p => path === p || path.startsWith(p + '/')) ? 'ca' : 'expense';
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [context, setContext] = useState<AppContext>(() => contextFromPath(pathname));

  return (
    <div className="shell">
      <Sidebar context={context} onContextChange={setContext} />
      <main className="main">{children}</main>
    </div>
  );
}
