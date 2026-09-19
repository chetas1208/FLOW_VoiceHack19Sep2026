import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ApprovalCard } from '../components/ApprovalCard';
import { RecommendationCard, TaskPanel, GoalPanel, VoicePanel } from '../components/cockpit/AgentPanels';
import { ControlBar } from '../components/cockpit/Controls';
import { CockpitHeader } from '../components/cockpit/Header';
import { ScoreStage } from '../components/cockpit/ScoreStage';
import { Timeline } from '../components/cockpit/Timeline';
import { EmptyState, Spinner } from '../components/primitives';
import { useDocumentTitle } from '../lib/hooks';
import { useSessionLive } from '../realtime/useSessionLive';
import { agentStatus, currentRecommendation, featuredTask, pendingApprovals } from '../store/selectors';
import { useStore } from '../store/store';
import { ApiError } from '../lib/api';

type Tab = 'state' | 'timeline' | 'agent';

export default function CockpitPage() {
  const { id = '' } = useParams();
  const load = useSessionLive(id);
  const slice = useStore((s) => s.sessions[id]);
  const devices = useStore((s) => s.devices);
  const allCommands = useStore((s) => s.commands);
  const [tab, setTab] = useState<Tab>('state');
  useDocumentTitle(slice?.session?.goal ?? 'Session');

  const commands = useMemo(
    () => Object.values(allCommands).filter((c) => c.session_id === id).sort((a, b) => b.created_at.localeCompare(a.created_at)),
    [allCommands, id],
  );

  if (!slice?.hydrated) {
    if (load.error) {
      const nf = (load.error as ApiError).code === 'not_found';
      return <EmptyState title={nf ? 'Session not found' : 'Could not load this session'} action={<button className="btn btn-secondary" onClick={load.reload}>Try again</button>}>{nf ? 'It may belong to another account, or the link is wrong.' : load.error.message}</EmptyState>;
    }
    return <div className="page-loading"><Spinner label="Loading session" /></div>;
  }

  const session = slice.session!;
  const device = devices[session.device_id];
  const presence = slice.presence?.state ?? device?.presence.state ?? 'offline';
  const ended = session.status === 'completed' || session.status === 'failed';
  const approvals = pendingApprovals(slice);
  const rec = currentRecommendation(slice);
  const task = featuredTask(slice);
  const agent = agentStatus(slice);
  const blocked = ended ? 'This session has ended.' : presence === 'offline' ? 'The device is offline. This cannot be queued.' : null;
  const ctx = { sessionId: id, deviceId: session.device_id, blocked };

  return (
    <div className="cockpit" data-tab={tab}>
      <CockpitHeader slice={slice} presence={presence} deviceName={session.device_name ?? device?.name ?? 'Device'} />

      {ended && (
        <div className="banner banner-ok ck-banner" role="status">
          <span>This session {session.status === 'failed' ? 'failed' : 'is complete'}.</span>
          <Link className="btn btn-primary btn-sm" to={`/session/${id}/report`}>View final report</Link>
        </div>
      )}
      {!ended && presence === 'offline' && (
        <div className="banner banner-warn ck-banner" role="alert">
          <div>
            <strong>Your device is offline.</strong>
            <span> Pause, Stop and Mute are queued and run when it reconnects. Everything else is disabled until then.</span>
          </div>
        </div>
      )}
      {!ended && presence === 'degraded' && (
        <div className="banner banner-caution ck-banner" role="status"><span>The device is online but reporting a problem with one of its components. Results may be delayed.</span></div>
      )}
      {!ended && slice.conn === 'unauthorized' && (
        <div className="banner banner-bad ck-banner" role="alert"><span>Live updates stopped because you are signed out.</span><Link className="btn btn-secondary btn-sm" to="/login">Sign in</Link></div>
      )}
      {approvals.length > 0 && tab !== 'agent' && (
        <button type="button" className="action-bar" onClick={() => setTab('agent')}>
          <span className="action-flag">ACTION NEEDED</span>
          <span>{approvals.length === 1 ? (approvals[0]!.action?.summary ?? 'An action') : `${approvals.length} actions`} waiting for your approval</span>
          <b>Review</b>
        </button>
      )}

      <div className="ck-tabs" role="tablist" aria-label="Cockpit sections">
        {([['state', 'State'], ['timeline', 'Timeline'], ['agent', 'Agent']] as const).map(([k, label]) => (
          <button key={k} role="tab" type="button" aria-selected={tab === k} className={tab === k ? 'is-on' : ''} onClick={() => setTab(k)}>
            {label}{k === 'agent' && approvals.length > 0 && <span className="tab-badge" aria-label={`${approvals.length} waiting`}>{approvals.length}</span>}
          </button>
        ))}
      </div>

      <div className="ck-grid">
        <div className="ck-col ck-state" data-pane="state">
          <ScoreStage slice={slice} />
          <GoalPanel slice={slice} />
        </div>
        <div className="ck-col ck-timeline" data-pane="timeline"><Timeline slice={slice} /></div>
        <div className="ck-col ck-agent" data-pane="agent">
          <header className="agent-head">
            <h2>FLOW agent</h2>
            <span className={`agent-state agent-${agent}`}>{agent === 'working' ? 'Working' : agent === 'needs_approval' ? 'Needs you' : 'Idle'}</span>
          </header>
          {approvals.map((a) => <ApprovalCard key={a.id} approval={a} deviceId={session.device_id} disabledReason={presence === 'offline' ? 'The device is offline. Approvals cannot be queued.' : ended ? 'This session has ended.' : null} />)}
          {rec ? <RecommendationCard key={rec.id} rec={rec} ctx={ctx} /> : <section className="card rec-empty"><h3>Next action</h3><p className="muted">No recommendation right now. FLOW will suggest something when it sees a good moment.</p></section>}
          <TaskPanel task={task} tools={task ? slice.tools[task.id] ?? [] : []} ctx={ctx} />
          <VoicePanel slice={slice} />
        </div>
      </div>

      <ControlBar slice={slice} presence={presence} commands={commands} />
    </div>
  );
}
