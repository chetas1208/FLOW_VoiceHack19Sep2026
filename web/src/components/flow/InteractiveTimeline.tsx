import { useState } from 'react';

const SEGMENTS = [
  { kind: 'away', flex: '1', label: 'Away', time: '10:12', range: '10:12–10:20', detail: 'Away from desk', align: '—' },
  { kind: 'focused', flex: '1', label: 'Focused', time: '10:28', range: '10:28–10:41', detail: 'Implementing auth flow', align: '91%' },
  { kind: 'focused short', flex: '.45', label: 'Focused', time: '10:52', range: '10:52–10:58', detail: 'Reading tests', align: '88%' },
  { kind: 'mixed', flex: '1', label: 'Mixed', time: '11:05', range: '11:05–11:22', detail: 'Context switching', align: '62%' },
  { kind: 'agent', flex: '1', label: 'Agent', time: '1:42', range: '1:42–1:55', detail: 'Agent-assisted fix', align: '95%' },
] as const;

export function InteractiveTimeline({
  onSelect,
  live,
  preview = true,
  compact,
  onOpenActivity,
}: {
  onSelect: (message: string) => void;
  live?: boolean;
  preview?: boolean;
  compact?: boolean;
  onOpenActivity?: () => void;
}) {
  const [active, setActive] = useState<number | null>(null);
  const showSegments = live || preview;
  const activeSeg = active !== null ? SEGMENTS[active] : null;

  return (
    <section className={`glass-panel timeline-panel level-2${compact ? ' timeline-compact' : ''}`} aria-label="Session timeline">
      <header>
        <strong>Timeline</strong>
        <span className="timeline-legend"><i /> Focused <i className="blue" /> Mixed <i className="gray" /> Away <i className="violet" /> Agent</span>
        {onOpenActivity && (
          <button type="button" className="timeline-activity-btn" onClick={onOpenActivity}>View activity</button>
        )}
        {live && <time className="timeline-elapsed">—</time>}
      </header>
      {!showSegments ? (
        <p className="timeline-empty">No active session — timeline fills in when flow start is running on your device.</p>
      ) : (
        <>
          {activeSeg && (
            <p className="timeline-hover-meta">{activeSeg.range} · {activeSeg.detail} · Alignment {activeSeg.align}</p>
          )}
          <div className="timeline-track timeline-track-interactive" role="group" aria-label="Timeline segments">
            {SEGMENTS.map((seg, index) => (
              <button
                key={`${seg.time}-${index}`}
                type="button"
                className={`timeline-seg ${seg.kind}${active === index ? ' is-active' : ''}`}
                style={{ flex: seg.flex }}
                aria-pressed={active === index}
                title={`${seg.range} · ${seg.detail}`}
                onClick={() => {
                  setActive(index);
                  onSelect(`${seg.label} · ${seg.range} · ${live ? seg.detail : 'preview'}`);
                }}
              />
            ))}
            <span className="timeline-now" aria-hidden="true" />
          </div>
          <footer><span>Start</span><strong>{live ? 'Now' : 'Preview'}</strong></footer>
        </>
      )}
    </section>
  );
}
