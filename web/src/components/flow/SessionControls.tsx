import { FlowIcon } from './FlowIcon';

export function SessionControls({
  paused,
  muted,
  stopped,
  disabled,
  onPause,
  onMute,
  onAsk,
  onDelegate,
  onStop,
}: {
  paused: boolean;
  muted: boolean;
  stopped: boolean;
  disabled?: boolean;
  onPause: () => void;
  onMute: () => void;
  onAsk: () => void;
  onDelegate: () => void;
  onStop: () => void;
}) {
  return (
    <nav className="session-controls" aria-label="Session controls">
      <button type="button" disabled={disabled} onClick={onPause}><FlowIcon>{paused || stopped ? '▶' : 'Ⅱ'}</FlowIcon>{paused || stopped ? 'Resume' : 'Pause'}</button>
      <button type="button" disabled={disabled} onClick={onMute}><FlowIcon>◖</FlowIcon>{muted ? 'Unmute' : 'Mute'}</button>
      <button type="button" disabled={disabled} onClick={onAsk}><FlowIcon>⌁</FlowIcon>Ask FLOW</button>
      <button type="button" disabled={disabled} onClick={onDelegate}><FlowIcon>➤</FlowIcon>Delegate</button>
      <button type="button" className="stop" disabled={disabled} onClick={onStop}><FlowIcon>■</FlowIcon>Stop</button>
    </nav>
  );
}
