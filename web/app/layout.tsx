import type { Metadata } from 'next';
import '@/lib/tokens/ink-navy.css';
import './globals.css';
import { AppShell } from '@/components/app-shell';

export const metadata: Metadata = {
  title: 'Finance Tracker',
  description: 'Personal finance tracking and CA-style health view',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
