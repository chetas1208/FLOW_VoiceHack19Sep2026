#!/usr/bin/env node
/**
 * FLOW server entry point: wires the modules together and starts listening.
 */
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { createStore } from './store/sessions.js';
import { createSettingsStore } from './server/settings.js';
import { createEventHub } from './server/events.js';
import { createAnalyzer } from './analyze/index.js';
import { createCoach } from './coach/index.js';
import { createObservationRuntime } from './observe/runtime.js';
import { createServer } from './server/http.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const DATA_DIR = process.env.FLOW_DATA_DIR || path.join(ROOT, 'data');

export async function start({ port = Number(process.env.PORT || 8080), host, dataDir = DATA_DIR, quiet = false } = {}) {
  const store = createStore({ file: process.env.FLOW_DATA_FILE || path.join(dataDir, 'sessions.json') });
  const settings = createSettingsStore({ file: path.join(dataDir, 'settings.json') });
  const hub = createEventHub();

  const analyzer = createAnalyzer({
    provider: settings.get().analyzer.provider,
    onStatus: (status) => hub.broadcast({ type: 'analyzer.status', analyzer: status }),
  });
  const coach = createCoach({
    onEvent: (event, intervention) => hub.broadcast({ type: event.type, sessionId: intervention.sessionId, event, intervention }),
  });

  const runtime = createObservationRuntime({ store, analyzer, coach, hub, settings }).start();

  const heartbeat = setInterval(() => hub.heartbeat(), 20000);
  heartbeat.unref?.();
  // Live sessions accrue unobserved time; recompute so the cockpit stays truthful.
  const refresh = setInterval(() => runtime.refreshLiveMetrics(), 15000);
  refresh.unref?.();

  await analyzer.probe(settings.get().privacy);

  const app = createServer({ store, settings, hub, analyzer, coach, runtime });
  const address = await app.listen(port, host);
  const url = `http://${address.address === '::1' ? '[::1]' : address.address}:${address.port}`;

  if (!quiet) {
    const perms = await runtime.permissions();
    const voice = await coach.voiceAvailable();
    console.log(`\n  FLOW  ·  session intelligence\n`);
    console.log(`  Dashboard        ${url}`);
    console.log(`  Data             ${store.file}`);
    console.log(`  UI               ${app.staticRoot.built ? 'built (app/dist)' : 'NOT BUILT — run `npm run build`'}`);
    console.log(`  Analyzer         ${analyzer.status.provider}${analyzer.status.model ? ` (${analyzer.status.model})` : ''} · ${analyzer.status.modality}`);
    console.log(`  Screen recording ${perms.screenRecording}`);
    console.log(`  Accessibility    ${perms.accessibility}`);
    console.log(`  Voice            ${voice.ok ? coach.voiceProviderName : `unavailable (${voice.reason})`}`);
    if (store.loadError) console.log(`  ⚠ Data           ${store.loadError}`);
    console.log('');
  }

  const shutdown = async () => {
    clearInterval(heartbeat);
    clearInterval(refresh);
    runtime.stop();
    await app.close();
  };

  return { url, address, store, settings, hub, analyzer, coach, runtime, close: shutdown };
}

const isEntry = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isEntry) {
  const instance = await start();
  for (const sig of ['SIGINT', 'SIGTERM']) {
    process.on(sig, async () => {
      await instance.close();
      process.exit(0);
    });
  }
}
