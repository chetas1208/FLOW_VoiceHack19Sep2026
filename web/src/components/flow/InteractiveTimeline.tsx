import { useState } from 'react';

const SEGMENTS = [
  { kind: 'away', flex: '1', label: 'Away', time: '10:12' },
  { kind: 'focused', flex: '1', label: 'Focused', time: '10:28' },
  { kind: 'focused short', flex: '.45', label: 'Focused', time: '10:52' },
  { kind: 'mixed', flex: '1', label: 'Mixed', time: '11:05' },
  { kind: 'away small', flex: '.32', label: 'Away', time: '11:18' },
  { kind: 'mixed long', flex: '1.8', label: 'Mixed', time: '11:40' },
  { kind: 'focused', flex: '1', label: 'Focused', time: '12:10' },
  { kind: 'agent small', flex: '.32', label: 'Agent', time: '12:45' },
  { kind: 'focused long', flex: '1.8', label: 'Focused', time: '1:05' },
  { kind: 'agent', flex: '1', label: 'Agent', time: '1:42' },
] as const;

export function InteractiveTimeline({ onSelect, live }: { onSelect: (message: string) => void; live?: boolean }) {
  const [active, setActive] = useState<number | null>(null);
  const hint = live
    ? 'Click a block to inspect focus context (sample layout until your session streams data).'
    : 'Timeline preview — live blocks appear during an active session on your device.';

  return (
    <section className="glass-panel timeline-panel" aria-label="Session timeline">
      <header><strong>Session Timeline</strong><span><i /> Focused <i className="blue" /> Mixed <i className="gray" /> Away <i className="violet" /> Agent</span></header>
      <p className="timeline-hint">{hint}</p>
      <div className="timeline-track timeline-track-interactive" role="group" aria-label="Timeline segments">
        {SEGMENTS.map((seg, index) => (
          <button
            key={`${seg.time}-${index}`}
            type="button"
            className={`timeline-seg ${seg.kind}${active === index ? ' is-active' : ''}`}
            style={{ flex: seg.flex }}
            aria-pressed={active === index}
            onClick={() => {
              setActive(index);
              onSelect(`${seg.label} block · ${seg.time} — ${live ? 'sample segment' : 'preview only'}`);
            }}
          />
        ))}
        <span className="timeline-now" aria-hidden="true" />
      </div>
      <footer><span>10:00</span><span>11:00</span><span>12:00</span><span>1:00</span><span>2:00</span><strong>Now</strong></footer>
    </section>
  );
}
