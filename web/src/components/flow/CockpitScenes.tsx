import sessionScene from '../../assets/flow-session-scene.png';
import agentScene from '../../assets/flow-agent-scene.png';
import { FlowIcon } from './FlowIcon';

export const WORKSPACE_STAGES = [
  { label: 'Understand', symbol: '⌕', detail: 'Clarify the goal and gather context from your machine.', activity: 'Reading project context' },
  { label: 'Plan', symbol: '▤', detail: 'Break work into verifiable steps with clear checkpoints.', activity: 'Planning next steps' },
  { label: 'Implement', symbol: '</>', detail: 'Make focused changes with evidence at each step.', activity: 'Implementing on device' },
  { label: 'Validate', symbol: '☑', detail: 'Run tests and checks — nothing ships without proof.', activity: 'Validating changes' },
  { label: 'Complete', symbol: '⚑', detail: 'Close the goal when evidence matches intent.', activity: 'Wrapping up session' },
] as const;

export function SessionHeroScene({
  deviceLabel,
  sublabel,
  activity,
  onEditorClick,
  onDaemonClick,
}: {
  deviceLabel: string;
  sublabel: string;
  activity?: string;
  onEditorClick?: () => void;
  onDaemonClick?: () => void;
}) {
  return (
    <figure className="flow-scene session-scene" aria-label="A developer working at a multi-monitor desk">
      <img src={sessionScene} alt="" />
      <div className="scene-vignette" aria-hidden="true" />
      <button type="button" className="scene-card editor-card scene-card-btn" onClick={onEditorClick}>
        <FlowIcon>⌘</FlowIcon><span>{deviceLabel}<small>{sublabel}</small></span>
      </button>
      <button type="button" className="scene-card test-card scene-card-btn" onClick={onDaemonClick}>
        <FlowIcon>⌁</FlowIcon><span>Local FLOW<small>On your machine</small></span>
      </button>
      <figcaption>GOOD THINGS TAKE FOCUS</figcaption>
      {activity && <span className="scene-state" aria-hidden="true">{activity}</span>}
    </figure>
  );
}

export function AgentHeroScene({ activity, onPanelClick }: { activity?: string; onPanelClick?: () => void }) {
  return (
    <figure className="flow-scene agent-scene" aria-label="A helpful FLOW agent at a workspace">
      <img src={agentScene} alt="" />
      <div className="scene-vignette" aria-hidden="true" />
      <button type="button" className="agent-float-card agent-analysis agent-float-btn" onClick={onPanelClick}>
        <strong><FlowIcon>✦</FlowIcon> FLOW agent</strong>
        <span>✓ &nbsp; Linked to your account</span>
        <span>○ &nbsp; Waiting for session work</span>
        <span>○ &nbsp; Tools ready on device</span>
      </button>
      <button type="button" className="agent-float-card agent-files agent-float-btn" onClick={onPanelClick}>
        <small>▱ Your workspace</small><span>↳ Local files only</span><span>↳ Safe execute</span>
      </button>
      {activity && <span className="scene-state" aria-hidden="true">{activity}</span>}
    </figure>
  );
}

export function SessionTimelineTrack() {
  return (
    <section className="glass-panel timeline-panel" aria-label="Session timeline">
      <header><strong>Session Timeline</strong><span><i /> Focused <i className="blue" /> Mixed <i className="gray" /> Away <i className="violet" /> Agent</span></header>
      <div className="timeline-track" aria-hidden="true"><b className="away" /><b className="focused" /><b className="focused short" /><b className="mixed" /><b className="away small" /><b className="mixed long" /><b className="focused" /><b className="mixed long" /><b className="agent small" /><b className="away" /><b className="focused" /><b className="focused long" /><b className="mixed long" /><b className="mixed short" /><b className="agent" /><span /></div>
      <footer><span>10:00</span><span>11:00</span><span>12:00</span><span>1:00</span><span>2:00</span><strong>Now</strong></footer>
    </section>
  );
}
