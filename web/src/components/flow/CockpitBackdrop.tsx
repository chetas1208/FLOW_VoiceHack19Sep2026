import sessionScene from '../../assets/flow-session-scene.png';
import agentScene from '../../assets/flow-agent-scene.png';

export function CockpitBackdrop({ variant }: { variant: 'session' | 'agent' }) {
  const src = variant === 'session' ? sessionScene : agentScene;
  return (
    <div className={`cockpit-backdrop is-${variant}`} aria-hidden="true">
      <img src={src} alt="" />
      <div className="cockpit-backdrop-vignette" />
      <div className="cockpit-backdrop-shade" />
    </div>
  );
}
