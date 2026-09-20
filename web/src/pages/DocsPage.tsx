import { useState } from 'react';
import { Link } from 'react-router-dom';

const repository = 'https://github.com/chetas1208/FLOW_VoiceHack19Sep2026.git';

function installCommand() {
  return `python3 -m pip install --user "git+${repository}"`;
}

export function DocsPage() {
  const [copied, setCopied] = useState('');
  const accountUrl = window.location.origin;
  const steps = [
    { title: 'Install the local CLI', command: installCommand(), detail: 'Installs the local-first FLOW command. It does not download a model.' },
    { title: 'Point it at this FLOW account', command: `export FLOW_ACCOUNT_URL=${accountUrl}`, detail: 'This only selects the account-control endpoint.' },
    { title: 'Authorize this computer', command: 'flow login', detail: 'Your terminal opens a five-minute, PKCE-protected browser approval. FLOW stores its device credential in your OS keychain when available.' },
    { title: 'Start the local runtime', command: 'flow daemon start', detail: 'The daemon and all session data stay on your computer.' },
  ];

  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(value);
      window.setTimeout(() => setCopied(''), 1600);
    } catch { setCopied('Copy failed — select the command manually.'); }
  }

  return <main className="docs-page">
    <header className="docs-header"><Link to="/app" className="docs-brand">FLOW</Link><Link to="/app" className="docs-back">← Workspace</Link></header>
    <section className="docs-hero">
      <p className="account-kicker">LOCAL-FIRST CONNECTION</p><h1>Connect FLOW to<br />your computer.</h1>
      <p>Sign in here, run the local CLI, and approve the one-time device request in this browser. Your account stores identity and device metadata only.</p>
    </section>
    <section className="docs-grid" aria-label="FLOW installation instructions">
      {steps.map((step, index) => <article className="docs-step" key={step.title}>
        <span>{index + 1}</span><h2>{step.title}</h2><p>{step.detail}</p>
        <div className="docs-command"><code>{step.command}</code><button type="button" onClick={() => copy(step.command)}>{copied === step.command ? 'Copied' : 'Copy'}</button></div>
      </article>)}
    </section>
    <section className="docs-policy">
      <div><h2>500 MB model budget</h2><p>FLOW does not load a browser or cloud model. The local runtime starts model-off; its model manager refuses artifacts estimated above 500 MB. Synchronous tools and deterministic session controls remain available without a model.</p></div>
      <div><h2>What stays local</h2><p>Screen observations, screenshots, session timelines, prompts, agent tool logs, code, voice transcripts, and SQLite history never go to Neon. The account service retains only user, device, authorization, and credential metadata.</p></div>
    </section>
    <p className="docs-foot">Already installed? Run <code>flow login</code> in a terminal, then return to this browser to approve the device.</p>
  </main>;
}
