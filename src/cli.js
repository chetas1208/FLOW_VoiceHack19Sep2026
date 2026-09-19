#!/usr/bin/env node
/**
 * FLOW command line.
 *
 * The CLI is how a session starts — it must be faster than opening a form.
 * It talks to the same HTTP API as the dashboard, so CLI and web never diverge.
 */
const BASE = process.env.FLOW_URL || 'http://127.0.0.1:8080';
const TOKEN = process.env.FLOW_AUTH_TOKEN || null;

const C = process.stdout.isTTY && !process.env.NO_COLOR
  ? { dim: (s) => `\x1b[2m${s}\x1b[0m`, b: (s) => `\x1b[1m${s}\x1b[0m`, cyan: (s) => `\x1b[36m${s}\x1b[0m`, green: (s) => `\x1b[32m${s}\x1b[0m`, amber: (s) => `\x1b[33m${s}\x1b[0m`, red: (s) => `\x1b[31m${s}\x1b[0m`, violet: (s) => `\x1b[35m${s}\x1b[0m` }
  : new Proxy({}, { get: () => (s) => s });

async function api(route, method = 'GET', body) {
  let res;
  try {
    res = await fetch(BASE + route, {
      method,
      headers: { 'Content-Type': 'application/json', ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error(`Could not reach the FLOW server at ${BASE}.\n  Start it in another terminal with:  npm start`);
  }
  const text = await res.text();
  let json;
  try {
    json = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(`Server returned a non-JSON response (${res.status})`);
  }
  if (!res.ok) {
    const detail = json.issues?.length ? `\n  ${json.issues.map((i) => `${i.path}: ${i.message}`).join('\n  ')}` : '';
    throw new Error((json.error || res.statusText) + detail);
  }
  return json;
}

const post = (id, action, body = {}) => api(`/api/sessions/${encodeURIComponent(id)}/${action}`, 'POST', body);
const pct = (v) => (v === null || v === undefined ? C.dim('no data') : `${v}%`);
const dur = (ms) => {
  const t = Math.max(0, Math.round(ms / 1000));
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  return h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m ${String(t % 60).padStart(2, '0')}s`;
};

const STATUS_COLOR = { live: C.green, paused: C.amber, stopped: C.dim };

function help() {
  console.log(`
${C.b('FLOW')} ${C.dim('· local work-session intelligence')}

  ${C.dim('Start the server first:')}  npm start

${C.b('Sessions')}
  flow start "<goal>" [--observe] [--screenshots] [--voice]
  flow list [--status live|paused|stopped] [--search <text>]
  flow status <id>
  flow pause|resume|stop <id>
  flow delete <id>

${C.b('Observation')}
  flow observe <id> "<app>" "<window title>"   ${C.dim('record one observation manually')}
  flow watch <id>                              ${C.dim('follow the live event stream')}

${C.b('Coach')}
  flow voice <id> on|off
  flow mute <id> [minutes]     flow unmute <id>

${C.b('Output')}
  flow report <id> [--json]
  flow evidence <id>
  flow export <id> > session.json

${C.b('System')}
  flow doctor                  ${C.dim('permissions, analyzer and voice status')}
  flow demo                    ${C.dim('run the deterministic end-to-end demo')}

${C.dim(`Server: ${BASE}`)}
`);
}

function printSessionHeader(s) {
  const color = STATUS_COLOR[s.status] || C.dim;
  console.log(`\n  ${C.b(s.goal)}`);
  console.log(`  ${C.dim(s.id)}  ${color(`● ${s.status.toUpperCase()}`)}  ${C.dim(dur(new Date(s.endedAt || Date.now()) - new Date(s.startedAt)))}`);
}

function printMetrics(m) {
  if (!m) return console.log(`  ${C.dim('No metrics yet — no observations have been recorded.')}`);
  console.log(`
  ${C.b(m.sessionScore === null ? '—' : String(m.sessionScore))}${C.dim('/100')}  ${C.cyan(m.band)}   ${C.dim(`confidence ${m.confidence ?? '—'} · coverage ${m.coverage ?? '—'}`)}

    Goal alignment      ${pct(m.goalAlignment)}
    Focus continuity    ${pct(m.focusContinuity)}
    Context stability   ${pct(m.contextStability)}
    Progress signal     ${pct(m.progressSignal)}

  ${C.dim(`Observed ${dur(m.durationsMs.observed)} · unobserved ${dur(m.durationsMs.unobserved)} · paused ${dur(m.durationsMs.paused)}`)}
  ${C.dim(m.method.label)}`);
}

async function main() {
  const argv = process.argv.slice(2);
  const command = argv[0];
  const args = argv.slice(1);
  const flag = (name) => argv.includes(`--${name}`);
  const opt = (name) => {
    const i = argv.indexOf(`--${name}`);
    return i >= 0 ? argv[i + 1] : undefined;
  };
  const positional = args.filter((a, i) => !a.startsWith('--') && !(i > 0 && args[i - 1]?.startsWith('--') && ['status', 'search'].includes(args[i - 1].slice(2))));

  if (!command || ['help', '--help', '-h'].includes(command)) return help();

  if (command === 'doctor') {
    const meta = await api('/api/meta');
    const ok = (b) => (b ? C.green('✓') : C.red('✗'));
    console.log(`\n  ${C.b('FLOW doctor')}  ${C.dim(`api v${meta.apiVersion} · ${meta.platform} · node ${meta.node}`)}\n`);
    console.log(`  ${ok(meta.uiBuilt)} Dashboard UI        ${meta.uiBuilt ? 'built' : C.amber('not built — run `npm run build`')}`);
    console.log(`  ${ok(meta.permissions.accessibility === 'granted')} Accessibility       ${meta.permissions.accessibility} ${C.dim('(window titles)')}`);
    console.log(`  ${ok(meta.permissions.screenRecording === 'granted')} Screen recording    ${meta.permissions.screenRecording} ${C.dim('(screenshots)')}`);
    console.log(`  ${ok(meta.permissions.helper)} Capture helper      ${meta.permissions.helper ? 'built' : C.amber('not built — run `npm run build:native`')}`);
    console.log(`  ${ok(meta.analyzer.state === 'ready')} Analyzer            ${meta.analyzer.provider}${meta.analyzer.model ? ` (${meta.analyzer.model})` : ''} · ${meta.analyzer.modality}`);
    console.log(`  ${ok(meta.voice.available)} Voice               ${meta.voice.provider}${meta.voice.available ? '' : C.amber(` — ${meta.voice.reason}`)}`);
    console.log(`  ${C.dim('  Data file          ')} ${meta.dataFile}`);
    console.log(`  ${C.dim('  Network binding    ')} ${meta.remoteAccess}`);
    if (meta.permissions.detail) console.log(`\n  ${C.amber('→')} ${meta.permissions.detail}`);
    if (meta.analyzer.note) console.log(`  ${C.dim('→ ' + meta.analyzer.note)}`);
    console.log('');
    return undefined;
  }

  if (command === 'demo') {
    const { runDemo } = await import('../scripts/demo.mjs');
    return runDemo({ base: BASE });
  }

  if (command === 'start') {
    const goal = positional.join(' ').trim();
    if (!goal) throw new Error('Provide a goal in quotes, e.g. flow start "Fix JWT authentication"');
    const s = await api('/api/sessions', 'POST', {
      goal,
      observe: flag('observe'),
      screenshots: flag('screenshots'),
      voice: flag('voice'),
    });
    const meta = await api('/api/meta');
    console.log(`\n  ${C.b('FLOW')} ${C.dim('v1.0')}\n`);
    console.log(`  ${C.green('✓')} Session created      ${C.b(s.id)}`);
    console.log(`  ${s.capture.enabled ? C.green('✓') : C.dim('·')} Screen observer      ${s.capture.enabled ? 'active' : 'manual (no capture)'}`);
    console.log(`  ${meta.analyzer.state === 'ready' ? C.green('✓') : C.amber('!')} Semantic analyzer    ${meta.analyzer.provider} · ${meta.analyzer.modality}`);
    console.log(`  ${s.voice.enabled ? C.green('✓') : C.dim('·')} Voice coach          ${s.voice.enabled ? `armed (intervenes only on sustained drift, ${s.voice.cooldownMinutes}m cooldown)` : 'off'}`);
    console.log(`  ${C.cyan('→')} Dashboard            ${BASE}/session/${s.id}/live`);
    console.log(`\n  ${C.dim('Privacy')}`);
    console.log(`  ${C.dim(`  Screenshots        ${s.privacy.screenshotsEnabled ? s.privacy.retention : 'not captured'}`)}`);
    console.log(`  ${C.dim(`  Analysis           ${s.privacy.analysisLocation}`)}`);
    console.log(`  ${C.dim(`  Excluded apps      ${s.privacy.excludedApps.slice(0, 5).join(', ')}${s.privacy.excludedApps.length > 5 ? `, +${s.privacy.excludedApps.length - 5} more` : ''}`)}`);
    if (s.capture.lastError) console.log(`\n  ${C.amber('!')} ${s.capture.lastError}`);
    console.log(`\n  ${C.dim(`flow pause ${s.id}  ·  flow stop ${s.id}  ·  flow mute ${s.id} 15`)}\n`);
    return undefined;
  }

  if (command === 'list') {
    const params = new URLSearchParams();
    if (opt('status')) params.set('status', opt('status'));
    if (opt('search')) params.set('q', opt('search'));
    const rows = await api(`/api/sessions${params.toString() ? `?${params}` : ''}`);
    if (!rows.length) return console.log(`\n  ${C.dim('No sessions yet. Start one:')} flow start "Fix the login bug"\n`);
    console.log('');
    for (const s of rows) {
      const color = STATUS_COLOR[s.status] || C.dim;
      const score = s.metrics?.sessionScore ?? null;
      console.log(
        `  ${C.dim(s.id)}  ${color(s.status.padEnd(7))} ${String(score === null ? '—' : score).padStart(3)}  ${C.dim(dur(s.durationMs).padStart(8))}  ${s.goal.slice(0, 54)}`,
      );
    }
    console.log(`\n  ${C.dim(`${rows.length} session(s)`)}\n`);
    return undefined;
  }

  const id = positional[0];
  if (!id) throw new Error(`"${command}" needs a session id. Run: flow list`);

  switch (command) {
    case 'status': {
      const s = await api(`/api/sessions/${encodeURIComponent(id)}`);
      printSessionHeader(s);
      printMetrics(s.metrics);
      if (s.latest || s.events?.length) {
        const latest = [...s.events].reverse().find((e) => e.type === 'observation.created');
        if (latest) {
          console.log(`\n  ${C.b('Now')}  ${latest.app}${latest.title ? ` ${C.dim('·')} ${latest.title}` : ''}`);
          console.log(`       ${C.violet(latest.category)} ${C.dim(`${Math.round(latest.confidence * 100)}% confidence (uncalibrated) · ${latest.analysis.provider}`)}`);
          console.log(`       ${C.dim(latest.reason)}`);
        }
      }
      console.log(`\n  ${C.b('Coach')} ${C.dim(s.coach.state)}${s.coach.suppressedReason ? `\n       ${C.dim(s.coach.suppressedReason)}` : ''}`);
      if (s.capture.lastError) console.log(`\n  ${C.amber('!')} ${s.capture.lastError}`);
      console.log('');
      return undefined;
    }
    case 'observe': {
      const app = positional[1];
      if (!app) throw new Error('Usage: flow observe <id> "<app>" "<window title>"');
      const r = await post(id, 'observe', { app, title: positional.slice(2).join(' ') });
      if (r.excluded) return console.log(`  ${C.dim('Excluded app — nothing was stored or analyzed.')}`);
      if (r.duplicate) return console.log(`  ${C.dim('Duplicate of the previous observation — not stored.')}`);
      console.log(`  ${C.violet(r.event.category)} ${C.dim(`${Math.round(r.event.confidence * 100)}%`)} — ${r.event.reason}`);
      if (r.intervention) console.log(`  ${C.magenta ? C.violet('◖))) coach:') : 'coach:'} "${r.intervention.transcript}"`);
      return undefined;
    }
    case 'pause':
    case 'resume':
    case 'stop': {
      const s = await post(id, command);
      console.log(`  ${C.b(s.id)}: ${(STATUS_COLOR[s.status] || C.dim)(s.status)}`);
      if (command === 'stop') {
        printMetrics(s.metrics);
        console.log(`\n  ${C.cyan('→')} Report: ${BASE}/session/${s.id}/report\n`);
      }
      return undefined;
    }
    case 'delete': {
      const r = await api(`/api/sessions/${encodeURIComponent(id)}`, 'DELETE');
      console.log(`  ${r.verified ? C.green('✓ deleted and verified removed from storage') : C.red('✗ deletion could not be verified')}`);
      return undefined;
    }
    case 'voice': {
      const s = await post(id, 'voice', { enabled: positional[1] === 'on' });
      console.log(`  Voice: ${s.voice.enabled ? C.green('ON') : C.dim('OFF')}`);
      return undefined;
    }
    case 'mute': {
      const s = await post(id, 'mute', { minutes: Number(positional[1]) || 15 });
      console.log(`  Coach muted until ${C.b(new Date(s.coach.muteUntil).toLocaleTimeString())}`);
      return undefined;
    }
    case 'unmute': {
      await post(id, 'unmute');
      console.log('  Coach unmuted.');
      return undefined;
    }
    case 'report': {
      const r = await api(`/api/sessions/${encodeURIComponent(id)}/report`);
      if (flag('json')) return console.log(JSON.stringify(r, null, 2));
      console.log(`\n  ${C.b(r.goal)}`);
      console.log(`  ${C.dim(`${new Date(r.startedAt).toLocaleString()} · ${r.durationLabel} · outcome: ${r.selfReportedOutcome || 'not recorded'}`)}`);
      printMetrics(r.metrics);
      console.log(`\n  ${C.b('Where time went')}`);
      for (const [k, v] of Object.entries(r.metrics.durationsMs)) {
        if (['aligned', 'away', 'classified', 'observed'].includes(k) || !v) continue;
        console.log(`    ${k.padEnd(12)} ${dur(v).padStart(9)}`);
      }
      console.log(`\n  ${C.b('Focus structure')}`);
      console.log(`    Longest block    ${dur(r.metrics.focus.longestBlockMs)}`);
      console.log(`    Median block     ${r.metrics.focus.medianBlockMs === null ? C.dim('no data') : dur(r.metrics.focus.medianBlockMs)}`);
      console.log(`    Context switches ${r.metrics.contextSwitches} ${C.dim(`(${r.metrics.switchDensityPerHour ?? '—'}/hour)`)}`);
      if (r.interventions.length) {
        console.log(`\n  ${C.b('Interventions')}`);
        for (const i of r.interventions) {
          console.log(`    ${new Date(i.triggeredAt).toLocaleTimeString()} ${C.violet(i.stage)} "${i.transcript}"`);
          console.log(`      ${C.dim(i.outcome.observation)}`);
        }
      }
      if (r.friction.length) {
        console.log(`\n  ${C.b('Top friction')}`);
        for (const f of r.friction) console.log(`    ${C.amber('•')} ${f.pattern}\n      ${C.dim(f.detail)}`);
      }
      console.log(`\n  ${C.b('Next-session experiment')}`);
      console.log(`    ${r.nextExperiment.experiment}`);
      console.log(`    ${C.dim(`Measure: ${r.nextExperiment.measure}`)}`);
      console.log(`\n  ${C.dim('Limitations')}`);
      for (const l of r.limitations) console.log(`    ${C.dim('· ' + l)}`);
      console.log('');
      return undefined;
    }
    case 'evidence': {
      const e = await api(`/api/sessions/${encodeURIComponent(id)}/evidence`);
      console.log(`\n  ${C.b(e.goal)}  ${C.dim(`coverage ${e.coverage === null ? '—' : Math.round(e.coverage * 100) + '%'}`)}\n`);
      for (const i of e.intervals) {
        const t = `${new Date(i.startedAt).toLocaleTimeString()}–${new Date(i.endedAt).toLocaleTimeString()}`;
        console.log(`  ${C.dim(t)}  ${C.violet(i.label.padEnd(15))} ${dur(i.durationMs).padStart(8)}  ${i.app || C.dim('—')}`);
        if (i.explanation) console.log(`      ${C.dim(i.explanation)}`);
        for (const ev of i.evidence.slice(0, 4)) console.log(`      ${C.dim('· ' + ev)}`);
        if (i.analysis) console.log(`      ${C.dim(`${i.analysis.provider}${i.analysis.model ? `/${i.analysis.model}` : ''} · ${i.analysis.modality} · screenshot: ${i.analysis.screenshotRetention}`)}`);
        console.log('');
      }
      return undefined;
    }
    case 'export': {
      const res = await fetch(`${BASE}/api/sessions/${encodeURIComponent(id)}/export`, { headers: TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {} });
      if (!res.ok) throw new Error(`Export failed (${res.status})`);
      process.stdout.write(await res.text());
      return undefined;
    }
    case 'watch': {
      console.log(`  ${C.dim(`Streaming events for ${id} — Ctrl-C to stop`)}\n`);
      const res = await fetch(`${BASE}/api/events`, { headers: { Accept: 'text/event-stream', ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}) } });
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const frames = buf.split('\n\n');
        buf = frames.pop() || '';
        for (const frame of frames) {
          const dataLine = frame.split('\n').find((l) => l.startsWith('data: '));
          if (!dataLine) continue;
          const payload = JSON.parse(dataLine.slice(6));
          if (payload.sessionId && payload.sessionId !== id) continue;
          const stamp = C.dim(new Date().toLocaleTimeString());
          if (payload.type === 'observation.created' && payload.event) {
            console.log(`  ${stamp} ${C.violet(payload.event.category.padEnd(12))} ${payload.event.app} ${C.dim(payload.event.title?.slice(0, 48) || '')}`);
          } else if (payload.type.startsWith('intervention.')) {
            console.log(`  ${stamp} ${C.amber(payload.type)} ${payload.intervention?.transcript || ''}`);
          } else {
            console.log(`  ${stamp} ${C.dim(payload.type)}`);
          }
        }
      }
      return undefined;
    }
    default:
      help();
      process.exitCode = 1;
      return undefined;
  }
}

main().catch((err) => {
  console.error(`\n  ${C.red('FLOW')} ${err.message}\n`);
  process.exitCode = 1;
});
