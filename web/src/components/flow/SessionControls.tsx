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
    <nav className="session-controls session-controls-grouped" aria-label="Session controls">
      <div className="control-group control-group-left">
        <button type="button" className="control-sm" disabled={disabled} onClick={onPause}><FlowIcon>{paused || stopped ? '▶' : 'Ⅱ'}</FlowIcon>{paused || stopped ? 'Resume' : 'Pause'}</button>
        <button type="button" className="control-sm" disabled={disabled} onClick={onMute}><FlowIcon>◖</FlowIcon>{muted ? 'Unmute' : 'Mute'}</button>
      </div>
      <div className="control-group control-group-center">
        <button type="button" className="control-sm" disabled={disabled} onClick={onAsk}><FlowIcon>⌁</FlowIcon>Ask FLOW</button>
        <button type="button" className="control-sm" disabled={disabled} onClick={onDelegate}><FlowIcon>➤</FlowIcon>Delegate</button>
      </div>
      <div className="control-group control-group-right">
        <button type="button" className="control-sm stop" disabled={disabled} onClick={onStop}><FlowIcon>■</FlowIcon>Stop</button>
      </div>
    </nav>
  );
}
