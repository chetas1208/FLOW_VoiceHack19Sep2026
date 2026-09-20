import sessionScene from '../../assets/flow-session-scene.png';
import agentScene from '../../assets/flow-agent-scene.png';
import { FlowIcon } from './FlowIcon';

export const WORKSPACE_STAGES = [
  { label: 'Understand', symbol: '⌕' },
  { label: 'Plan', symbol: '▤' },
  { label: 'Implement', symbol: '</>' },
  { label: 'Validate', symbol: '☑' },
  { label: 'Complete', symbol: '⚑' },
] as const;

export function SessionHeroScene({
  deviceLabel,
  sublabel,
  activity,
}: {
  deviceLabel: string;
  sublabel: string;
  activity?: string;
}) {
  return (
    <figure className="flow-scene session-scene" aria-label="A developer working at a multi-monitor desk">
      <img src={sessionScene} alt="" />
      <div className="scene-vignette" aria-hidden="true" />
      <div className="scene-card editor-card"><FlowIcon>⌘</FlowIcon><span>{deviceLabel}<small>{sublabel}</small></span></div>
      <div className="scene-card test-card"><FlowIcon>⌁</FlowIcon><span>Local FLOW<small>On your machine</small></span></div>
      <figcaption>GOOD THINGS TAKE FOCUS</figcaption>
      {activity && <span className="scene-state" aria-hidden="true">{activity}</span>}
    </figure>
  );
}

export function AgentHeroScene({ activity }: { activity?: string }) {
  return (
    <figure className="flow-scene agent-scene" aria-label="A helpful FLOW agent at a workspace">
      <img src={agentScene} alt="" />
      <div className="scene-vignette" aria-hidden="true" />
      <div className="agent-float-card agent-analysis">
        <strong><FlowIcon>✦</FlowIcon> FLOW agent</strong>
        <span>✓ &nbsp; Linked to your account</span>
        <span>○ &nbsp; Waiting for session work</span>
        <span>○ &nbsp; Tools ready on device</span>
      </div>
      <div className="agent-float-card agent-files"><small>▱ Your workspace</small><span>↳ Local files only</span><span>↳ Safe execute</span></div>
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
