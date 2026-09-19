import { useEffect, useRef } from 'react';
import { CATEGORY_LABEL } from '../../store/timeline';
import { pct } from '../../lib/format';
import type { SessionSlice, TrendPoint } from '../../store/reducer';
import { Chip, Meter } from '../primitives';

const band = (score: number | null) => (score === null ? ['Collecting signal', 'idle'] : score >= 75 ? ['Locked in', 'high'] : score >= 55 ? ['Steady', 'mid'] : score >= 35 ? ['Drifting', 'low'] : ['Off track', 'bad']) as [string, string];

const DRIFT_LABEL: Record<string, string> = { focused: 'Focused', mixed: 'Mixed', drifting: 'Drifting', sustained_drift: 'Sustained drift', recovering: 'Recovering', unknown: 'Unknown' };

export function Sparkline({ points }: { points: TrendPoint[] }) {
  const pts = points.slice(-60);
  if (pts.length < 2) return <div className="spark spark-empty">Trend appears after a few readings</div>;
  const w = 220, h = 52, pad = 4;
  const xs = (i: number) => pad + (i * (w - pad * 2)) / (pts.length - 1);
  const ys = (v: number) => h - pad - Math.max(0, Math.min(1, v)) * (h - pad * 2);
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${xs(i).toFixed(1)} ${ys(p.score).toFixed(1)}`).join(' ');
  const last = pts[pts.length - 1]!;
  const first = pts[0]!;
  const delta = Math.round((last.score - first.score) * 100);
  return (
    <figure className="spark" aria-label={`Score trend over the last ${pts.length} readings, ${delta >= 0 ? 'up' : 'down'} ${Math.abs(delta)} points`}>
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img" aria-hidden="true">
        <path d={`${d} L${xs(pts.length - 1)} ${h} L${xs(0)} ${h} Z`} className="spark-area" />
        <path d={d} className="spark-line" vectorEffect="non-scaling-stroke" />
        <circle cx={xs(pts.length - 1)} cy={ys(last.score)} r="3.2" className="spark-dot" />
      </svg>
      <figcaption>{delta >= 0 ? 'Up' : 'Down'} {Math.abs(delta)} over this window</figcaption>
    </figure>
  );
}

export function ScoreStage({ slice }: { slice: SessionSlice }) {
  const ref = useRef<HTMLElement>(null);
  const m = slice.metrics;
  const score = pct(m.session_score);
  const [word, tone] = band(score);
  const cur = slice.current;
  const drift = String(cur.drift ?? m.drift_state ?? 'unknown');

  // Depth parallax: pointer moves tilt the glass plates a few degrees. Disabled for reduced motion / coarse pointers.
  useEffect(() => {
    const el = ref.current;
    if (!el || window.matchMedia('(prefers-reduced-motion: reduce), (pointer: coarse)').matches) return;
    const move = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5;
      el.style.setProperty('--ry', `${(x * 7).toFixed(2)}deg`);
      el.style.setProperty('--rx', `${(-y * 5).toFixed(2)}deg`);
    };
    const leave = () => { el.style.setProperty('--ry', '0deg'); el.style.setProperty('--rx', '0deg'); };
    el.addEventListener('pointermove', move); el.addEventListener('pointerleave', leave);
    return () => { el.removeEventListener('pointermove', move); el.removeEventListener('pointerleave', leave); };
  }, []);

  return (
    <section ref={ref} className={`stage stage-${tone}`} aria-label="Session state">
      <div className="stage-plates" aria-hidden="true"><i style={{ ['--i' as string]: 3 }} /><i style={{ ['--i' as string]: 2 }} /><i style={{ ['--i' as string]: 1 }} /></div>
      <div className="stage-face">
        <div className="score-block">
          <p className="score" aria-label={score === null ? 'No score yet' : `Session score ${score} out of 100`}><span className="score-num">{score ?? '--'}</span></p>
          <p className="score-word">{word}</p>
          <p className="score-cap">Session score</p>
        </div>
        <Sparkline points={slice.trend} />
      </div>

      <div className="now">
        <div className="now-line">
          <i className={`cat cat-${cur.category ?? 'unknown'}`} aria-hidden="true" />
          <p className="now-activity">{cur.activity ?? 'Waiting for activity'}</p>
        </div>
        <div className="now-tags">
          {cur.category && <Chip tone={cur.category === 'distraction' ? 'bad' : cur.category === 'core_task' ? 'cyan' : 'neutral'}>{CATEGORY_LABEL[String(cur.category)] ?? cur.category}</Chip>}
          {cur.task_phase && <Chip tone="violet">{String(cur.task_phase).replace(/_/g, ' ')}</Chip>}
          <Chip tone={drift === 'focused' ? 'ok' : drift === 'unknown' ? 'neutral' : drift === 'mixed' || drift === 'recovering' ? 'warn' : 'bad'}>{DRIFT_LABEL[drift] ?? drift}</Chip>
        </div>
        {cur.blocker && (
          <div className="blocker" role="status">
            <strong>Blocker</strong>
            <span>{cur.blocker}</span>
          </div>
        )}
      </div>

      <dl className="gauges">
        {([['Alignment', m.goal_alignment, 'cyan'], ['Focus', m.focus_continuity, 'violet'], ['Progress', m.progress, 'ok']] as const).map(([label, v, tone]) => {
          const p = pct(v as number | null | undefined);
          return (
            <div key={label} className="gauge">
              <dt>{label}</dt>
              <dd><span className="gauge-val">{p === null ? '--' : p}<small>{p === null ? '' : '%'}</small></span><Meter value={p} tone={tone} label={label} /></dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}
