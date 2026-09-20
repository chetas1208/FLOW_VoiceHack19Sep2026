import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { AgentWorkspace } from '../components/flow/AgentWorkspace';
import { DocsTabPanel } from '../components/flow/DocsTabPanel';
import { FlowIcon } from '../components/flow/FlowIcon';
import { FlowWorkspaceHeader, type WorkspaceTab } from '../components/flow/FlowWorkspaceHeader';
import { SessionControls } from '../components/flow/SessionControls';
import { SessionWorkspace } from '../components/flow/SessionWorkspace';
import { ShowcaseTab } from '../components/flow/ShowcaseTab';
import { useFlowDevices } from '../hooks/useFlowDevices';
import { modelStatus, pairingState } from '../lib/flowDeviceModel';
import type { AccountUser } from '../lib/flowWorkspaceUi';

function parseTab(raw: string | null): WorkspaceTab {
  if (raw === 'agent' || raw === 'docs' || raw === 'showcase') return raw;
  return 'session';
}

export default function FlowWorkspacePage({ account }: { account?: AccountUser }) {
  const [params, setParams] = useSearchParams();
  const tab = parseTab(params.get('tab'));
  const { device, presence } = useFlowDevices();
  const pairing = pairingState(device);
  const [notice, setNotice] = useState('');
  const [privacyOpen, setPrivacyOpen] = useState(false);
  const [paused, setPaused] = useState(false);
  const [muted, setMuted] = useState(false);
  const [stopped, setStopped] = useState(false);

  const setTab = useCallback((next: WorkspaceTab) => {
    if (next === 'session') setParams({});
    else setParams({ tab: next });
  }, [setParams]);

  useEffect(() => {
    if (window.location.pathname.startsWith('/docs')) setParams({ tab: 'docs' }, { replace: true });
  }, [setParams]);

  const health = device?.presence.health ?? {};
  const footerModels = presence === 'online'
    ? [modelStatus(health.model), 'Kokoro TTS'].filter(Boolean)
    : ['Local models on your device'];

  return (
    <main className="flow-workspace" aria-label="FLOW workspace">
      <div className="flow-atmosphere" aria-hidden="true" />
      <div className={`flow-shell app-shell ${tab === 'agent' ? 'is-agent-view' : ''} ${tab === 'docs' ? 'is-docs-view' : ''} ${tab === 'showcase' ? 'is-showcase-view' : ''}`}>
        <FlowWorkspaceHeader
          tab={tab}
          onTabChange={setTab}
          device={device}
          pairing={pairing}
          presence={presence}
          account={account}
        />
        <div className="flow-main">
          {tab === 'session' && (
            <SessionWorkspace device={device} pairing={pairing} presence={presence} onDocs={() => setTab('docs')} />
          )}
          {tab === 'agent' && (
            <AgentWorkspace device={device} pairing={pairing} presence={presence} onDocs={() => setTab('docs')} />
          )}
          {tab === 'docs' && <DocsTabPanel />}
          {tab === 'showcase' && <ShowcaseTab onAnnounce={setNotice} />}
        </div>
        {tab === 'session' && pairing === 'paired' && (
          <SessionControls
            paused={paused}
            muted={muted}
            stopped={stopped}
            disabled={presence !== 'online'}
            onPause={() => { setPaused((v) => !v); setStopped(false); setNotice(paused ? 'Session resumed.' : 'Session paused.'); }}
            onMute={() => { setMuted((v) => !v); setNotice(muted ? 'FLOW audio unmuted.' : 'FLOW audio muted.'); }}
            onAsk={() => { setTab('agent'); setNotice('FLOW is ready for your direction.'); }}
            onDelegate={() => { setTab('agent'); setNotice('Delegation workspace opened.'); }}
            onStop={() => { setStopped(true); setPaused(true); setNotice('Session stopped.'); }}
          />
        )}
        <p className="flow-announcement" role="status" aria-live="polite">{notice}</p>
        <footer className="flow-footer">
          <button type="button" className="privacy-chip" onClick={() => setPrivacyOpen((v) => !v)}>🔒 Work data stays on your device</button>
          {privacyOpen && (
            <p className="privacy-pop">Session content, code, and observations remain on your linked machine. The account stores identity and device metadata only.</p>
          )}
          <span>
            <i aria-hidden="true" />
            {pairing === 'paired'
              ? (presence === 'online' ? 'Connected to your device' : `${device?.name ?? 'Device'} offline · still linked`)
              : 'Link a device to begin'}
          </span>
          {footerModels.map((label) => <b key={label}>{label}</b>)}
          <small><FlowIcon>♙</FlowIcon>All data stays on your machine. Always.</small>
        </footer>
      </div>
    </main>
  );
}
