import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type { FlowDevice } from '../../lib/account';
import { installCommand, TROUBLESHOOTING, DOC_NAV } from '../../lib/flowCommandsDoc';
import { ago, daemonStatus, modelStatus, pairingState, presenceLabel, type PresenceState } from '../../lib/flowDeviceModel';
import { CopyCommand, CopyCodeBlock, copyText } from './CopyCommand';

const SEARCH_INDEX = DOC_NAV.map((n) => ({ id: n.id, title: n.title }));

const TROUBLE_IDS = [
  { id: 'offline', label: 'Device offline' },
  { id: 'models', label: 'Models missing' },
  { id: 'screen', label: 'Screen permission' },
  { id: 'voice', label: 'Voice not working' },
  { id: 'cli', label: 'CLI not found' },
] as const;

export function DocsTabPanel({
  device,
  pairing,
  presence,
  accountName,
  onAnnounce,
}: {
  device: FlowDevice | null;
  pairing: ReturnType<typeof pairingState>;
  presence: PresenceState;
  accountName?: string;
  onAnnounce?: (msg: string) => void;
}) {
  const [section, setSection] = useState<(typeof DOC_NAV)[number]['id']>('quick-start');
  const [query, setQuery] = useState('');
  const [troubleId, setTroubleId] = useState<(typeof TROUBLE_IDS)[number]['id'] | null>(null);
  const [checkResult, setCheckResult] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);
  const accountUrl = window.location.origin;
  const install = installCommand();
  const paired = pairing === 'paired';
  const online = paired && presence === 'online';
  const health = device?.presence.health ?? {};

  const setupLines = useMemo(() => [install, 'flow setup', 'flow login', 'flow start "your goal"'], [install]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === '/' && !(e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement)) {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const filteredNav = query.trim()
    ? SEARCH_INDEX.filter((item) => item.title.toLowerCase().includes(query.trim().toLowerCase()))
    : SEARCH_INDEX;

  const stepInstall = { done: true, label: 'Install CLI', cmd: install };
  const stepSetup = { done: paired, label: 'Setup', cmd: 'flow setup' };
  const stepLogin = { done: paired, label: 'Connect account', cmd: 'flow login', status: paired ? `Connected${accountName ? ` as ${accountName}` : ''}` : undefined };
  const stepDaemon = { done: health.daemon === 'running', label: 'Daemon', cmd: 'flow daemon start', optional: !paired };
  const stepStart = { done: false, label: 'Start session', cmd: 'flow start "your goal"' };

  const highlightCmd = !paired
    ? null
    : !online
      ? 'flow daemon start'
      : health.model === 'not_installed'
        ? 'flow models install'
        : null;

  async function copyFullSetup() {
    const ok = await copyText(setupLines.join('\n'));
    onAnnounce?.(ok ? 'Copied full setup sequence.' : 'Copy failed — select text manually.');
  }

  function runCheck() {
    if (!paired) {
      setCheckResult('No linked device. Run flow login on your machine.');
      return;
    }
    setCheckResult(
      online
        ? 'Daemon reachable. Last heartbeat ' + ago(device?.presence.last_heartbeat_at ?? device?.last_seen_at ?? null) + '.'
        : `Daemon unreachable. Last heartbeat ${ago(device?.presence.last_heartbeat_at ?? device?.last_seen_at ?? null)}. Try flow daemon start on your device.`,
    );
  }

  const trouble = troubleId === 'offline'
    ? { title: 'Device offline', body: TROUBLESHOOTING[0]!.fix, cmd: 'flow daemon start' }
    : troubleId === 'models'
      ? { title: 'Models missing', body: TROUBLESHOOTING[3]!.fix, cmd: 'flow models install' }
      : troubleId === 'screen'
        ? { title: 'Screen permission', body: TROUBLESHOOTING[4]!.fix, cmd: 'flow permissions' }
        : troubleId === 'voice'
          ? { title: 'Voice not working', body: 'Run flow voice status on your device.', cmd: 'flow voice status' }
          : troubleId === 'cli'
            ? { title: 'CLI not found', body: 'Install the FLOW CLI using the install command.', cmd: install }
            : null;

  return (
    <section className="docs-tab docs-console" aria-label="FLOW documentation">
      <div className="docs-console-search">
        <input
          ref={searchRef}
          type="search"
          placeholder="Search docs… (/ to focus)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search documentation"
        />
      </div>
      <nav className="docs-tab-nav" aria-label="Documentation sections">
        {(query ? filteredNav : DOC_NAV).map((item) => (
          <button key={item.id} type="button" className={section === item.id ? 'is-active' : ''} onClick={() => { setSection(item.id as typeof section); setQuery(''); }}>
            {item.title}
          </button>
        ))}
      </nav>
      <div className="docs-tab-body docs-console-body">
        {section === 'quick-start' && (
          <>
            <div className="docs-console-head">
              <h2>Get started in 60 seconds</h2>
              <button type="button" className="copy-setup-all" onClick={() => void copyFullSetup()}>Copy full setup</button>
            </div>
            {highlightCmd && (
              <p className="docs-context-banner">Suggested next: <code>{highlightCmd}</code></p>
            )}
            <ol className="docs-quick-steps">
              <QuickStep n={1} step={stepInstall} collapsed={false} onCopied={() => onAnnounce?.('Copied install command.')} />
              <QuickStep n={2} step={stepSetup} collapsed={stepSetup.done} onCopied={() => onAnnounce?.('Copied flow setup.')} />
              <QuickStep
                n={3}
                step={stepLogin}
                collapsed={stepLogin.done}
                onCopied={() => onAnnounce?.('Copied flow login.')}
                status={stepLogin.done ? <span className="step-ok">Account connected ✓</span> : undefined}
              />
              {paired && !online && (
                <QuickStep n={4} step={stepDaemon} collapsed={stepDaemon.done} onCopied={() => onAnnounce?.('Copied daemon start.')} />
              )}
              <QuickStep n={paired && !online ? 5 : 4} step={stepStart} collapsed={false} onCopied={() => onAnnounce?.('Copied flow start.')} />
            </ol>
            <div className="docs-status-strip">
              <span>{stepInstall.done ? '✓ CLI install command ready' : '○ Install CLI'}</span>
              <span>{stepSetup.done ? '✓ Setup path linked' : '○ Setup'}</span>
              <span>{stepLogin.done ? '✓ Account linked' : '○ Connect account'}</span>
              <span>{online ? '✓ Daemon online' : paired ? '○ Start daemon' : '○ Start session'}</span>
            </div>
          </>
        )}
        {section === 'install' && (
          <>
            <h2>Install</h2>
            <CopyCommand command={install} label="Install CLI" hint="Run on your development machine." onCopied={() => onAnnounce?.('Copied.')} />
          </>
        )}
        {section === 'connect' && (
          <>
            <h2>Connect account</h2>
            <CopyCommand command={`export FLOW_ACCOUNT_URL=${accountUrl}`} label="Account URL" onCopied={() => onAnnounce?.('Copied.')} />
            <CopyCommand
              command="flow login"
              label="Login"
              hint="Approve this browser when prompted."
              status={paired ? <span className="step-ok">Connected{accountName ? ` as ${accountName}` : ''} ✓</span> : undefined}
              onCopied={() => onAnnounce?.('Copied.')}
            />
          </>
        )}
        {section === 'start' && (
          <>
            <h2>Start session</h2>
            <CopyCommand command='flow start "your goal"' onCopied={() => onAnnounce?.('Copied.')} />
            <CopyCommand command="flow daemon start" hint="If the web app shows your device offline." onCopied={() => onAnnounce?.('Copied.')} />
            <CopyCommand command="flow status" onCopied={() => onAnnounce?.('Copied.')} />
          </>
        )}
        {section === 'commands' && (
          <>
            <h2>Commands</h2>
            <CopyCodeBlock title="Common sequence" lines={['flow setup', 'flow login', 'flow daemon start', 'flow start "goal"']} onCopied={() => onAnnounce?.('Copied.')} />
          </>
        )}
        {section === 'troubleshoot' && (
          <>
            <h2>Troubleshooting</h2>
            <div className="trouble-chips">
              {TROUBLE_IDS.map((t) => (
                <button key={t.id} type="button" className={troubleId === t.id ? 'is-active' : ''} onClick={() => setTroubleId(t.id)}>{t.label}</button>
              ))}
            </div>
            {trouble && (
              <div className="trouble-detail glass-panel">
                <h3>{trouble.title}</h3>
                <p>{trouble.body}</p>
                <CopyCommand command={trouble.cmd} onCopied={() => onAnnounce?.('Copied.')} />
                {troubleId === 'offline' && (
                  <button type="button" className="secondary-action compact-action" onClick={runCheck}>Run check</button>
                )}
                {checkResult && <p className="check-result">{checkResult}</p>}
              </div>
            )}
            {!troubleId && (
              <ul className="docs-trouble">
                {TROUBLESHOOTING.map((row) => (
                  <li key={row.issue}><strong>{row.issue}</strong><span>{row.fix}</span></li>
                ))}
              </ul>
            )}
          </>
        )}
        {paired && section === 'quick-start' && (
          <p className="docs-device-meta">
            Device {device?.name} · {presenceLabel(presence)} · Daemon {daemonStatus(health.daemon, presence)} · Model {modelStatus(health.model)}
          </p>
        )}
      </div>
    </section>
  );
}

function QuickStep({
  n,
  step,
  collapsed,
  status,
  onCopied,
}: {
  n: number;
  step: { label: string; cmd: string; done?: boolean };
  collapsed: boolean;
  status?: ReactNode;
  onCopied: () => void;
}) {
  const [open, setOpen] = useState(!collapsed);
  useEffect(() => { setOpen(!collapsed); }, [collapsed]);

  if (collapsed && !open) {
    return (
      <li className="docs-quick-step is-done">
        <button type="button" className="docs-quick-step-toggle" onClick={() => setOpen(true)}>
          ✓ {step.label}
        </button>
      </li>
    );
  }

  return (
    <li className="docs-quick-step">
      <span className="docs-quick-step-n">{n}</span>
      <div>
        <strong>{step.label}</strong>
        <CopyCommand command={step.cmd} onCopied={onCopied} status={status} />
      </div>
    </li>
  );
}
