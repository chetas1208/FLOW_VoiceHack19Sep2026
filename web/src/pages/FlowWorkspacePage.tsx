import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { AgentWorkspace } from '../components/flow/AgentWorkspace';
import { DocsTabPanel } from '../components/flow/DocsTabPanel';
import { FlowDrawer } from '../components/flow/FlowDrawer';
import { FlowWorkspaceHeader, type WorkspaceTab } from '../components/flow/FlowWorkspaceHeader';
import { SessionControls } from '../components/flow/SessionControls';
import { SessionWorkspace } from '../components/flow/SessionWorkspace';
import { FlowToast } from '../components/flow/FlowToast';
import { ShowcaseTab } from '../components/flow/ShowcaseTab';
import { CockpitBackdrop } from '../components/flow/CockpitBackdrop';
import { useFlowDevices } from '../hooks/useFlowDevices';
import { modelStatus, pairingState, presenceLabel } from '../lib/flowDeviceModel';
import type { AccountUser } from '../lib/flowWorkspaceUi';

function parseTab(raw: string | null): WorkspaceTab {
  if (raw === 'agent' || raw === 'docs' || raw === 'showcase') return raw;
  return 'session';
}

const PRIVACY_ROWS = [
  ['Screen analysis', 'Local'],
  ['Screenshot retention', 'Off'],
  ['Account DB', 'Metadata only'],
  ['Models', 'Local'],
  ['Agent execution', 'Local'],
] as const;

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
  const [showcaseView, setShowcaseView] = useState<'session' | 'agent'>('session');

  const setTab = useCallback((next: WorkspaceTab) => {
    if (next === 'session') setParams({});
    else setParams({ tab: next });
  }, [setParams]);

  useEffect(() => {
    if (window.location.pathname.startsWith('/docs')) setParams({ tab: 'docs' }, { replace: true });
  }, [setParams]);

  useEffect(() => {
    if (tab !== 'showcase') setShowcaseView('session');
  }, [tab]);

  const health = device?.presence.health ?? {};
  const immersive = tab === 'session' || tab === 'agent' || tab === 'showcase' || tab === 'docs';
  const footerDevice = pairing === 'paired'
    ? `${device?.name ?? 'Device'} ● ${presence === 'online' ? 'Connected' : presenceLabel(presence)}`
    : 'Link a device';
  const footerModels = presence === 'online' && health.model
    ? modelStatus(health.model)
    : 'Models on device';

  return (
    <main className={`flow-workspace${immersive ? ' is-immersive' : ''}`} aria-label="FLOW workspace">
      {!immersive && <div className="flow-atmosphere" aria-hidden="true" />}
      <div className={`flow-shell app-shell ${tab === 'agent' ? 'is-agent-view' : ''} ${tab === 'docs' ? 'is-docs-view' : ''} ${tab === 'showcase' ? 'is-showcase-view' : ''}${immersive ? ' is-immersive-shell' : ''}`}>
        {immersive && (
          <CockpitBackdrop
            variant={tab === 'agent' || (tab === 'showcase' && showcaseView === 'agent') ? 'agent' : 'session'}
            key={`${tab}-${showcaseView}`}
          />
        )}
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
            <SessionWorkspace
              device={device}
              pairing={pairing}
              presence={presence}
              stopped={stopped}
              paused={paused}
              onDocs={() => setTab('docs')}
              onAnnounce={setNotice}
              onGoAgent={() => setTab('agent')}
            />
          )}
          {tab === 'agent' && (
            <AgentWorkspace device={device} pairing={pairing} presence={presence} onDocs={() => setTab('docs')} onAnnounce={setNotice} />
          )}
          {tab === 'docs' && (
            <DocsTabPanel
              device={device}
              pairing={pairing}
              presence={presence}
              accountName={account?.name}
              onAnnounce={setNotice}
            />
          )}
          {tab === 'showcase' && <ShowcaseTab onAnnounce={setNotice} onViewChange={setShowcaseView} />}
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
        <FlowToast message={notice} onClear={() => setNotice('')} />
        <footer className="flow-footer flow-footer-compact">
          <button type="button" className="privacy-chip" onClick={() => setPrivacyOpen(true)}>🔒 Local-first</button>
          <span><i className={presence === 'online' ? 'online' : ''} aria-hidden="true" />{footerDevice}</span>
          <b>{footerModels}</b>
        </footer>
      </div>

      <FlowDrawer open={privacyOpen} title="Privacy" onClose={() => setPrivacyOpen(false)}>
        <dl className="privacy-drawer-list">
          {PRIVACY_ROWS.map(([label, value]) => (
            <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
          ))}
        </dl>
        <p className="drawer-empty">Session content and code stay on your linked machine. This account stores identity and device metadata only.</p>
      </FlowDrawer>
    </main>
  );
}
