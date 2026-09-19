import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { clock } from '../../lib/format';
import type { SessionSlice } from '../../store/reducer';
import { buildTimeline, type TimelineItem } from '../../store/timeline';
import { Icon } from '../Icon';

function Row({ item }: { item: TimelineItem }) {
  return (
    <li className={`tl tl-${item.lane} tone-${item.tone}`}>
      <div className="tl-card">
        <p className="tl-title">{item.title}{item.count > 1 && <span className="tl-count" title={`${item.count} readings`}> x{item.count}</span>}</p>
        {item.detail && <p className="tl-detail">{item.detail}</p>}
        <time className="tl-time" dateTime={item.ts}>{clock(item.ts)}</time>
      </div>
      <i className="tl-node" aria-hidden="true" />
    </li>
  );
}

export function Timeline({ slice }: { slice: SessionSlice }) {
  const items = useMemo(() => buildTimeline(slice.events), [slice.events]);
  const scroller = useRef<HTMLDivElement>(null);
  const [pinned, setPinned] = useState(true);
  const [unseen, setUnseen] = useState(0);
  const lastCount = useRef(0);

  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    if (pinned) { el.scrollTop = el.scrollHeight; setUnseen(0); }
    else setUnseen((u) => u + Math.max(0, items.length - lastCount.current));
    lastCount.current = items.length;
  }, [items, pinned]);

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const on = () => setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 48);
    el.addEventListener('scroll', on, { passive: true });
    return () => el.removeEventListener('scroll', on);
  }, []);

  const jump = () => { const el = scroller.current; if (el) { el.scrollTo({ top: el.scrollHeight, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' }); setPinned(true); } };

  return (
    <section className="runway" aria-label="Live timeline">
      <header className="runway-head">
        <h2>Live timeline</h2>
        <div className="lane-keys"><span className="key key-human"><i />Human</span><span className="key key-agent"><i />Agent</span></div>
      </header>
      <div className="runway-stage">
        <div className="runway-plane">
          <div className="lane-titles" aria-hidden="true"><span>You</span><span>FLOW agent</span></div>
          <div className="runway-scroll" ref={scroller} tabIndex={0} role="log" aria-live="off" aria-label="Timeline events, newest at the bottom">
            {items.length === 0 ? <p className="tl-empty">Waiting for the first activity from the device.</p> : <ol className="lanes">{items.map((it) => <Row key={it.id} item={it} />)}</ol>}
          </div>
        </div>
        {!pinned && (
          <button type="button" className="jump" onClick={jump}><Icon name="down2" size={16} />{unseen > 0 ? `${unseen} new` : 'Latest'}</button>
        )}
      </div>
    </section>
  );
}
