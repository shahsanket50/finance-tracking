import { redirect } from 'next/navigation';

// Phase 2.5 landing: Audit is the only built screen.
// Phase 3.5 will redirect to /home once the dashboard exists.
export default function Page() {
  redirect('/audit');
}
