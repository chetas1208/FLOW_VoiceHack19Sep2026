import { CopyCommand } from './CopyCommand';

export function SetupStrip({
  variant,
  onDocs,
  onCopied,
}: {
  variant: 'unpaired' | 'offline';
  onDocs: () => void;
  onCopied: (msg: string) => void;
}) {
  return (
    <div className="setup-strip glass-panel level-2">
      <div className="setup-strip-copy">
        <strong>{variant === 'unpaired' ? 'Connect your machine' : 'Wake your device'}</strong>
        <p>
          {variant === 'unpaired'
            ? 'FLOW runs locally. Link this browser to your CLI — nothing executes in the cloud.'
            : 'Your device is still paired. Start the daemon on your machine and this cockpit reconnects.'}
        </p>
      </div>
      <div className="setup-strip-actions">
        {variant === 'unpaired' ? (
          <CopyCommand command="flow login" label="1 · Login" onCopied={() => onCopied('Copied flow login.')} />
        ) : (
          <CopyCommand command="flow daemon start" label="1 · Daemon" onCopied={() => onCopied('Copied flow daemon start.')} />
        )}
        <CopyCommand command='flow start "your goal"' label="2 · Session" onCopied={() => onCopied('Copied flow start.')} />
        <button type="button" className="secondary-action compact-action" onClick={onDocs}>Open Docs</button>
      </div>
    </div>
  );
}
