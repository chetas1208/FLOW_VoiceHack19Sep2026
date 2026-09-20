import { FlowIcon } from './FlowIcon';

export type ActivityRow = { time: string; icon: string; label: string; detail: string };

export function SessionActivityDrawerContent({ rows, empty }: { rows: ActivityRow[]; empty?: string }) {
  if (!rows.length) {
    return <p className="drawer-empty">{empty ?? 'Activity appears when a session is running on your device.'}</p>;
  }
  return (
    <ul className="activity-drawer-list">
      {rows.map((row) => (
        <li key={`${row.time}-${row.label}`}>
          <time>{row.time}</time>
          <FlowIcon>{row.icon}</FlowIcon>
          <span><strong>{row.label}</strong><small>{row.detail}</small></span>
        </li>
      ))}
    </ul>
  );
}
