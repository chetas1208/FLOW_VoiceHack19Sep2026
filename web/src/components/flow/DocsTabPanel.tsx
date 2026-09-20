import { useState } from 'react';
import { CORE_COMMANDS, DOC_NAV, installCommand, TROUBLESHOOTING } from '../../lib/flowCommandsDoc';

export function DocsTabPanel() {
  const [section, setSection] = useState<(typeof DOC_NAV)[number]['id']>('quick-start');
  const [copied, setCopied] = useState('');
  const accountUrl = window.location.origin;
  const install = installCommand();

  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(value);
      window.setTimeout(() => setCopied(''), 1600);
    } catch {
      setCopied('failed');
    }
  }

  return (
    <section className="docs-tab" aria-label="FLOW documentation">
      <nav className="docs-tab-nav" aria-label="Documentation sections">
        {DOC_NAV.map((item) => (
          <button key={item.id} type="button" className={section === item.id ? 'is-active' : ''} onClick={() => setSection(item.id)}>
            {item.title}
          </button>
        ))}
      </nav>
      <div className="docs-tab-body">
        {section === 'quick-start' && (
          <>
            <h2>Quick Start</h2>
            <ol className="docs-steps">
              <li>Install the CLI</li>
              <li><code>flow setup</code></li>
              <li><code>flow login</code> and approve in this browser</li>
              <li><code>flow daemon start</code></li>
              <li><code>flow start &quot;your goal&quot;</code></li>
            </ol>
          </>
        )}
        {section === 'install' && (
          <>
            <h2>Install</h2>
            <CommandBlock command={install} copied={copied} onCopy={copy} />
            <p className="docs-note">Or clone the repo and run <code>pip install -e .</code> from the project root.</p>
          </>
        )}
        {section === 'connect' && (
          <>
            <h2>Connect Account</h2>
            <CommandBlock command={`export FLOW_ACCOUNT_URL=${accountUrl}`} copied={copied} onCopy={copy} />
            <CommandBlock command="flow login" copied={copied} onCopy={copy} />
          </>
        )}
        {section === 'start' && (
          <>
            <h2>Start Session</h2>
            <CommandBlock command='flow start "Finish authentication and pass all tests"' copied={copied} onCopy={copy} />
            <CommandBlock command="flow status" copied={copied} onCopy={copy} />
          </>
        )}
        {section === 'commands' && (
          <>
            <h2>FLOW commands</h2>
            {CORE_COMMANDS.map((group) => (
              <div key={group.group} className="docs-command-group">
                <h3>{group.group}</h3>
                <ul>{group.items.map((cmd) => <li key={cmd}><code>{cmd}</code></li>)}</ul>
              </div>
            ))}
          </>
        )}
        {section === 'troubleshoot' && (
          <>
            <h2>Troubleshooting</h2>
            <ul className="docs-trouble">
              {TROUBLESHOOTING.map((row) => (
                <li key={row.issue}><strong>{row.issue}</strong><span>{row.fix}</span></li>
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
  );
}

function CommandBlock({ command, copied, onCopy }: { command: string; copied: string; onCopy: (v: string) => void }) {
  return (
    <div className="docs-command">
      <code>{command}</code>
      <button type="button" onClick={() => onCopy(command)}>{copied === command ? 'Copied' : 'Copy'}</button>
    </div>
  );
}
