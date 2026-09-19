import { useEffect, useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Chip, EmptyState, Spinner } from '../components/primitives';
import { api, ApiError } from '../lib/api';
import { clock, dateTime, humanDuration, pct } from '../lib/format';
import { useDocumentTitle } from '../lib/hooks';
import type { SessionReport } from '../lib/types';

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const str = (v: unknown): string => (typeof v === 'string' ? v : v == null ? '' : JSON.stringify(v));
const list = (v: unknown): Array<Record<string, any>> => (Array.isArray(v) ? v.filter((x) => x && typeof x === 'object') : []);

function Section({ title, children, empty }: { title: string; children?: ReactNode; empty?: string }) {
  return (
    <section className="rep-section">
      <h2>{title}</h2>
      {children ?? <p className="muted">{empty ?? 'Nothing to show.'}</p>}
    </section>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return <div className="stat"><dd>{value}</dd><dt>{label}</dt>{note && <small className="muted">{note}</small>}</div>;
}

export default function ReportPage() {
  const { id = '' } = useParams();
  const [report, setReport] = useState<SessionReport | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  useDocumentTitle('Session report');

  useEffect(() => {
    let live = true;
    api.report(id).then((r) => live && setReport(r)).catch((e) => live && setError(e));
    return () => { live = false; };
  }, [id]);

  if (error) return <EmptyState title={error.code === 'not_found' ? 'Report not found' : 'Could not load the report'} action={<Link to="/sessions" className="btn btn-secondary">Back to sessions</Link>}>{error.message}</EmptyState>;
  if (!report) return <div className="page-loading"><Spinner label="Loading report" /></div>;

  const m = report.metrics ?? {};
  const score = pct(num(report.score) ?? num(m.session_score));
  const hva = report.human_vs_agent ?? {};
  const human = num(hva.human_seconds) ?? num(hva.human) ?? 0;
  const agent = num(hva.agent_seconds) ?? num(hva.agent) ?? 0;
  const total = human + agent;
  const segments = list(report.segments);
  const segTotal = segments.reduce((a, s) => a + Math.max(0, (new Date(str(s.ended_at ?? s.end)).getTime() - new Date(str(s.started_at ?? s.start)).getTime()) || 0), 0);
  const tasks = list(report.tasks), approvals = list(report.approvals), recs = list(report.recommendations);
  const blockers = list(report.blockers), drifts = list(report.drift_periods), voice = list(report.voice_interventions), ints = list(report.interventions);
  const duration = num(report.duration_seconds);

  return (
    <article className="report">
      <header className="rep-hero">
        <div>
          <p className="muted small"><Link to="/sessions" className="link-quiet">Sessions</Link> / Final report</p>
          <h1>{report.goal ?? report.session?.goal ?? 'Session report'}</h1>
          <p className="muted">{report.started_at && dateTime(report.started_at)}{duration !== null && <> for {humanDuration(duration)}</>}</p>
        </div>
        <div className="rep-score" aria-label={score === null ? 'No score' : `Score ${score} out of 100`}>
          <span>{score ?? '--'}</span><small>Session score</small>
        </div>
      </header>

      <dl className="stats">
        <Stat label="Goal alignment" value={pct(num(m.goal_alignment)) === null ? '--' : `${pct(num(m.goal_alignment))}%`} />
        <Stat label="Focus" value={pct(num(m.focus_continuity)) === null ? '--' : `${pct(num(m.focus_continuity))}%`} note={num(m.longest_focus_block) ? `Longest block ${humanDuration(num(m.longest_focus_block)!)}` : undefined} />
        <Stat label="Context stability" value={pct(num(m.context_stability)) === null ? '--' : `${pct(num(m.context_stability))}%`} note={num(m.context_switches) !== null ? `${m.context_switches} switches` : undefined} />
        <Stat label="Progress" value={pct(num(m.progress)) === null ? '--' : `${pct(num(m.progress))}%`} />
        <Stat label="Coverage" value={pct(num(m.coverage)) === null ? '--' : `${pct(num(m.coverage))}%`} note="How much of the session FLOW could see" />
        <Stat label="Confidence" value={pct(num(m.confidence)) === null ? '--' : `${pct(num(m.confidence))}%`} />
      </dl>

      <Section title="Human and agent">
        {total > 0 ? (
          <div className="split">
            <div className="split-bar" role="img" aria-label={`You ${humanDuration(human)}, agent ${humanDuration(agent)}`}>
              <span className="split-h" style={{ flexGrow: human }} /><span className="split-a" style={{ flexGrow: agent }} />
            </div>
            <p><span className="key key-human"><i />You</span> {humanDuration(human)} <span className="key key-agent"><i />Agent</span> {humanDuration(agent)}</p>
          </div>
        ) : <p className="muted">No agent work was recorded in this session.</p>}
      </Section>

      <Section title="How the time went" empty="No segments were recorded.">
        {segments.length > 0 && (
          <>
            <div className="segbar" role="img" aria-label="Session segments by category">
              {segments.map((s, i) => {
                const dur = Math.max(0, new Date(str(s.ended_at ?? s.end)).getTime() - new Date(str(s.started_at ?? s.start)).getTime()) || 1;
                return <span key={i} className={`seg cat-${str(s.category) || 'unknown'}`} style={{ flexGrow: dur / (segTotal || 1) }} title={str(s.label ?? s.summary ?? s.category)} />;
              })}
            </div>
            <ul className="seg-list">{segments.slice(0, 12).map((s, i) => <li key={i}><i className={`cat cat-${str(s.category) || 'unknown'}`} aria-hidden="true" />{str(s.label ?? s.summary ?? s.category)}</li>)}</ul>
          </>
        )}
      </Section>

      <div className="rep-cols">
        <Section title="Blockers" empty="No blockers.">{blockers.length > 0 && <ul className="plain">{blockers.map((b, i) => <li key={i}>{str(b.text ?? b.blocker ?? b.summary)}{b.started_at && <small className="muted"> at {clock(str(b.started_at))}</small>}</li>)}</ul>}</Section>
        <Section title="Drift periods" empty="No drift.">{drifts.length > 0 && <ul className="plain">{drifts.map((d, i) => <li key={i}>{clock(str(d.started_at ?? d.start))} to {d.ended_at || d.end ? clock(str(d.ended_at ?? d.end)) : 'end'}{d.state && <Chip tone="warn">{str(d.state).replace(/_/g, ' ')}</Chip>}</li>)}</ul>}</Section>
      </div>

      <Section title="Agent work" empty="The agent did not run any tasks.">
        {tasks.length > 0 && (
          <ul className="plain rows">
            {tasks.map((t, i) => <li key={i}><Chip tone={t.status === 'completed' ? 'ok' : t.status === 'failed' ? 'bad' : 'neutral'}>{str(t.status)}</Chip><span>{str(t.instruction)}</span>{t.result?.summary && <small className="muted">{str(t.result.summary)}</small>}</li>)}
          </ul>
        )}
        {approvals.length > 0 && (
          <>
            <h3>Approvals</h3>
            <ul className="plain rows">{approvals.map((a, i) => <li key={i}><Chip tone={a.status === 'approved' ? 'ok' : a.status === 'denied' ? 'bad' : 'neutral'}>{str(a.status)}</Chip><span>{str(a.action?.summary ?? a.action)}</span><small className="muted">{str(a.risk)} risk</small></li>)}</ul>
          </>
        )}
      </Section>

      <div className="rep-cols">
        <Section title="Recommendations" empty="None.">{recs.length > 0 && <ul className="plain rows">{recs.map((r, i) => <li key={i}><Chip tone={r.status === 'accepted' ? 'ok' : 'neutral'}>{str(r.status)}</Chip><span>{str(r.title)}</span>{r.feedback && <small className="muted">{str(r.feedback).replace(/_/g, ' ')}</small>}</li>)}</ul>}</Section>
        <Section title="What FLOW said" empty="FLOW stayed quiet.">{(voice.length > 0 || ints.length > 0) && <ul className="plain rows">{(voice.length ? voice : ints).map((v, i) => <li key={i}><span>{str(v.message ?? v.reason)}</span>{(v.timestamp || v.delivered_at) && <small className="muted">{clock(str(v.timestamp ?? v.delivered_at))}</small>}</li>)}</ul>}</Section>
      </div>
    </article>
  );
}
