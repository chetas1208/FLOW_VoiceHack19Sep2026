/**
 * FLOW HTTP API.
 *
 * Bound to 127.0.0.1 by default. There is no authentication because there is no
 * remote surface: binding elsewhere is refused unless FLOW_ALLOW_REMOTE=1 is set
 * *and* a token is configured, so the unauthenticated API can never be exposed
 * by accident.
 */
import http from 'node:http';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import { timingSafeEqual, randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';

import { API_VERSION, CATEGORY_COLORS, CATEGORY_LABELS, CATEGORIES, DEFAULT_EXCLUDED_APPS } from '../domain/contracts.js';
import { ObservationInputSchema, PrivacySettingsSchema, VoiceSettingsSchema, StartSessionSchema } from '../domain/contracts.js';
import { parse, ValidationError } from '../domain/schema.js';
import * as Session from '../domain/session.js';
import { buildIntervals } from '../temporal/intervals.js';
import { computeMetrics } from '../temporal/metrics.js';
import { analyseInterventionOutcome } from '../coach/index.js';
import { requestScreenRecordingPermission } from '../observe/macos.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
  '.map': 'application/json; charset=utf-8',
};

/** Where the built UI lives; falls back to the legacy vanilla app if not built. */
function resolveStaticRoot() {
  const dist = path.join(ROOT, 'app', 'dist');
  if (fs.existsSync(path.join(dist, 'index.html'))) return { dir: dist, built: true };
  return { dir: path.join(ROOT, 'public'), built: false };
}

export function createServer({ store, settings, hub, analyzer, coach, runtime }) {
  const staticRoot = resolveStaticRoot();
  const remoteToken = process.env.FLOW_AUTH_TOKEN || null;
  const allowRemote = process.env.FLOW_ALLOW_REMOTE === '1';

  /** Exact-origin CORS allowlist, e.g. FLOW_ALLOWED_ORIGINS=https://flow.vercel.app. */
  const allowedOrigins = (process.env.FLOW_ALLOWED_ORIGINS || '')
    .split(',')
    .map((s) => s.trim().replace(/\/+$/, ''))
    .filter(Boolean);

  function applyCors(req, res) {
    const origin = (req.headers.origin || '').replace(/\/+$/, '');
    if (!origin || !allowedOrigins.includes(origin)) return;
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Vary', 'Origin');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    res.setHeader('Access-Control-Max-Age', '86400');
    // Private Network Access: the API lives on a tailnet (CGNAT) address, so a
    // public HTTPS origin (e.g. Vercel) must be explicitly allowed to reach it.
    res.setHeader('Access-Control-Allow-Private-Network', 'true');
  }

  const json = (res, status, body) => {
    const payload = JSON.stringify(body ?? null);
    res.writeHead(status, {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
      'Content-Length': Buffer.byteLength(payload),
    });
    res.end(payload);
  };

  const fail = (res, err) => {
    const status = err.status || (err instanceof ValidationError ? 400 : 500);
    if (status >= 500) console.error('[flow]', err);
    json(res, status, { error: err.message, issues: err.issues || undefined });
  };

  async function readBody(req) {
    let data = '';
    for await (const chunk of req) {
      data += chunk;
      if (data.length > 2_000_000) throw Object.assign(new Error('Request body too large'), { status: 413 });
    }
    if (!data) return {};
    try {
      return JSON.parse(data);
    } catch {
      throw Object.assign(new Error('Request body is not valid JSON'), { status: 400 });
    }
  }

  const mustGet = (id) => {
    const s = store.get(id);
    if (!s) throw Object.assign(new Error(`Session ${id} was not found`), { status: 404 });
    return s;
  };

  const publish = (type, session, extra = {}) => {
    store.set(session);
    hub.broadcast({ type, sessionId: session.id, session, ...extra });
    return session;
  };

  /** Token check for the opt-in remote mode. Constant-time. */
  function authorised(req) {
    if (!remoteToken) return true;
    const header = req.headers.authorization || '';
    const provided = Buffer.from(header.replace(/^Bearer\s+/i, ''));
    const expected = Buffer.from(remoteToken);
    return provided.length === expected.length && timingSafeEqual(provided, expected);
  }

  async function serveStatic(req, res, pathname) {
    const { dir, built } = resolveStaticRoot();
    let rel = decodeURIComponent(pathname).replace(/^\/+/, '');
    if (!rel) rel = 'index.html';

    // Resolve, then verify the result is still inside the static root.
    let full = path.resolve(dir, rel);
    if (!full.startsWith(dir + path.sep) && full !== dir) full = path.join(dir, 'index.html');

    let stat = null;
    try {
      stat = await fsp.stat(full);
    } catch { /* fall through to SPA */ }

    if (!stat || stat.isDirectory()) {
      // SPA fallback: unknown paths render the app shell, not a 404.
      full = path.join(dir, 'index.html');
      try {
        await fsp.stat(full);
      } catch {
        return json(res, 404, {
          error: 'The FLOW user interface has not been built yet.',
          fix: 'Run `npm run build` to build the dashboard, or `npm run dev` for the development server.',
        });
      }
    }

    const ext = path.extname(full);
    const body = await fsp.readFile(full);
    const immutable = built && /\/assets\//.test(full);
    res.writeHead(200, {
      'Content-Type': MIME[ext] || 'application/octet-stream',
      'Cache-Control': immutable ? 'public, max-age=31536000, immutable' : 'no-store',
      'X-Content-Type-Options': 'nosniff',
      'Referrer-Policy': 'no-referrer',
      // The dashboard loads nothing from the network; lock it down accordingly.
      'Content-Security-Policy':
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; font-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; object-src 'none'",
    });
    res.end(body);
  }

  const server = http.createServer(async (req, res) => {
    try {
      applyCors(req, res);
      if (req.method === 'OPTIONS') {
        res.writeHead(204);
        res.end();
        return;
      }
      const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
      const p = url.pathname;

      if (p.startsWith('/api/')) {
        if (!authorised(req)) return json(res, 401, { error: 'Unauthorized' });
        return await handleApi(req, res, url, p);
      }
      if (req.method !== 'GET' && req.method !== 'HEAD') return json(res, 405, { error: 'Method not allowed' });
      return await serveStatic(req, res, p);
    } catch (err) {
      fail(res, err);
    }
  });

  async function handleApi(req, res, url, p) {
    // ---- stream -------------------------------------------------------------
    if (p === '/api/events' && req.method === 'GET') {
      hub.subscribe(req, res, url.searchParams.get('since'));
      return undefined;
    }

    // ---- meta ---------------------------------------------------------------
    if (p === '/api/meta' && req.method === 'GET') {
      const perms = await runtime.permissions();
      const voiceCheck = await coach.voiceAvailable();
      return json(res, 200, {
        apiVersion: API_VERSION,
        platform: process.platform,
        node: process.version,
        dataFile: store.file,
        loadError: store.loadError,
        uiBuilt: staticRoot.built,
        permissions: perms,
        analyzer: analyzer.status,
        voice: { provider: coach.voiceProviderName, describe: coach.describeVoice(), available: voiceCheck.ok, reason: voiceCheck.reason || null },
        categories: CATEGORIES.map((c) => ({ key: c, label: CATEGORY_LABELS[c], color: CATEGORY_COLORS[c] })),
        defaultExcludedApps: DEFAULT_EXCLUDED_APPS,
        streamSeq: hub.seq,
        remoteAccess: allowRemote ? 'enabled' : 'localhost-only',
      });
    }

    if (p === '/api/voices' && req.method === 'GET') return json(res, 200, await coach.listVoices());

    if (p === '/api/permissions/screen-recording' && req.method === 'POST') {
      const result = await requestScreenRecordingPermission();
      runtime.invalidatePermissions();
      return json(res, 200, { ...result, permissions: await runtime.permissions() });
    }

    if (p === '/api/analyzer/probe' && req.method === 'POST') {
      const status = await analyzer.probe(settings.get().privacy);
      hub.broadcast({ type: 'analyzer.status', analyzer: status });
      return json(res, 200, status);
    }

    // ---- settings -----------------------------------------------------------
    if (p === '/api/settings') {
      if (req.method === 'GET') return json(res, 200, settings.get());
      if (req.method === 'POST') {
        const body = await readBody(req);
        const patch = {};
        if (body.privacy) patch.privacy = parse(PrivacySettingsSchema, body.privacy);
        if (body.voice) patch.voice = parse(VoiceSettingsSchema, body.voice);
        if (body.observer) patch.observer = body.observer;
        if (body.analyzer) patch.analyzer = body.analyzer;
        const next = settings.update(patch);
        hub.broadcast({ type: 'settings.changed', settings: next });
        return json(res, 200, next);
      }
      return json(res, 405, { error: 'Method not allowed' });
    }

    // ---- destructive: delete every session ----------------------------------
    if (p === '/api/data' && req.method === 'DELETE') {
      const count = store.deleteAll();
      hub.broadcast({ type: 'data.deleted', deletedSessions: count });
      return json(res, 200, {
        deletedSessions: count,
        dataFile: store.file,
        verified: store.all().length === 0,
        note: 'All session records were removed from the data file. Screenshots are never retained beyond analysis unless retention was explicitly enabled.',
      });
    }

    // ---- sessions collection ------------------------------------------------
    if (p === '/api/sessions') {
      if (req.method === 'GET') {
        const q = (url.searchParams.get('q') || '').toLowerCase();
        const status = url.searchParams.get('status');
        let rows = store.all().map(Session.summarise);
        if (q) rows = rows.filter((s) => s.goal.toLowerCase().includes(q) || s.id.toLowerCase().includes(q));
        if (status && status !== 'all') rows = rows.filter((s) => s.status === status);
        rows.sort((a, b) => new Date(b.startedAt) - new Date(a.startedAt));
        return json(res, 200, rows);
      }
      if (req.method === 'POST') {
        const body = parse(StartSessionSchema, await readBody(req));
        const defaults = settings.get();
        const canObserve = body.observe && process.platform === 'darwin';
        const session = Session.createSession(body.goal, {
          observe: canObserve,
          screenshots: canObserve && body.screenshots,
          voice: body.voice ?? defaults.voice.enabled,
          simulated: body.simulated,
          mode: body.simulated ? 'simulated' : canObserve ? 'mac-observer' : 'manual',
          samplePeriodMs: defaults.observer.intervalMs,
          privacy: defaults.privacy,
        });
        session.voice = { ...session.voice, ...defaults.voice, enabled: body.voice ?? defaults.voice.enabled };
        session.capture.status = canObserve ? 'starting' : 'off';
        session.analyzer = await analyzer.probe(session.privacy);
        Session.appendEvent(session, { type: 'session.started', goal: session.goal });
        if (body.observe && !canObserve) {
          session.capture.lastError = `Screen observation requires macOS; this server runs on ${process.platform}. The session was created in manual mode.`;
        }
        return json(res, 201, publish('session.started', session));
      }
      return json(res, 405, { error: 'Method not allowed' });
    }

    // ---- single session -----------------------------------------------------
    const m = p.match(/^\/api\/sessions\/([^/]+)(?:\/([^/]+))?(?:\/([^/]+))?$/);
    if (!m) return json(res, 404, { error: 'Unknown endpoint' });

    const id = decodeURIComponent(m[1]);
    const action = m[2];
    const sub = m[3];

    if (req.method === 'GET' && !action) return json(res, 200, mustGet(id));

    if (req.method === 'DELETE' && !action) {
      const existed = store.delete(id);
      if (!existed) return json(res, 404, { error: `Session ${id} was not found` });
      hub.broadcast({ type: 'session.deleted', sessionId: id });
      return json(res, 200, { deleted: true, sessionId: id, verified: !store.has(id) });
    }

    if (req.method === 'GET' && action === 'report') {
      const s = mustGet(id);
      return json(res, 200, s.report || Session.buildReport(s));
    }

    if (req.method === 'GET' && action === 'export') {
      const s = mustGet(id);
      const payload = JSON.stringify({ exportedAt: Session.now(), apiVersion: API_VERSION, session: s, report: s.report || Session.buildReport(s) }, null, 2);
      res.writeHead(200, {
        'Content-Type': 'application/json; charset=utf-8',
        'Content-Disposition': `attachment; filename="flow-${s.id}.json"`,
        'Cache-Control': 'no-store',
      });
      return res.end(payload);
    }

    if (req.method === 'GET' && action === 'evidence') {
      const s = mustGet(id);
      const { intervals, coverage, observedMs, unobservedMs } = buildIntervals(s);
      return json(res, 200, {
        sessionId: s.id,
        goal: s.goal,
        coverage,
        observedMs,
        unobservedMs,
        privacy: s.privacy,
        intervals: intervals.map((i) => ({
          ...i,
          label: CATEGORY_LABELS[i.category] || i.category,
          color: CATEGORY_COLORS[i.category] || '#64748b',
          observations: s.events.filter((e) => i.observationIds.includes(e.id)),
        })),
        interventions: s.interventions.map((iv) => ({ ...iv, outcome: analyseInterventionOutcome(iv, intervals) })),
      });
    }

    if (req.method === 'GET' && action === 'timeline') {
      const s = mustGet(id);
      return json(res, 200, buildIntervals(s));
    }

    if (req.method !== 'POST') return json(res, 405, { error: 'Method not allowed' });

    const session = mustGet(id);
    const body = await readBody(req);

    switch (action) {
      case 'observe': {
        const input = parse(ObservationInputSchema, body);
        const result = await runtime.ingest(session, input);
        if (result.excluded) return json(res, 200, { excluded: true, reason: result.reason, stored: false });
        if (result.duplicate) return json(res, 200, { duplicate: true, stored: false });
        return json(res, 200, { event: result.event, intervention: result.intervention, session });
      }
      case 'pause':
        return json(res, 200, publish('session.paused', session, { event: Session.pauseSession(session) }));
      case 'resume':
        return json(res, 200, publish('session.resumed', session, { event: Session.resumeSession(session) }));
      case 'stop': {
        const event = Session.stopSession(session);
        if (!event) return json(res, 200, session);
        return json(res, 200, publish('session.stopped', session, { event }));
      }
      case 'capture': {
        if (typeof body.enabled === 'boolean') {
          if (body.enabled && process.platform !== 'darwin') {
            throw Object.assign(new Error(`Screen observation requires macOS; this server runs on ${process.platform}.`), { status: 400 });
          }
          session.capture.enabled = body.enabled;
          session.capture.status = body.enabled ? 'starting' : 'off';
          session.capture.lastError = null;
        }
        if (typeof body.screenshots === 'boolean') {
          session.privacy.screenshotsEnabled = body.screenshots;
          session.capture.screenshots = body.screenshots;
        }
        runtime.invalidatePermissions();
        return json(res, 200, publish('observer.status', session));
      }
      case 'privacy': {
        const patch = parse(PrivacySettingsSchema, body);
        for (const [k, v] of Object.entries(patch)) {
          if (v === null || v === undefined) continue;
          if (k === 'excludedApps') session.privacy.excludedApps = [...new Set(v.map((x) => x.trim()).filter(Boolean))];
          else session.privacy[k] = v;
        }
        // Selecting cloud analysis without consent must never silently enable it.
        if (session.privacy.analysisLocation === 'cloud' && !session.privacy.cloudConsent) {
          session.privacy.analysisLocation = 'metadata-only';
          session.analyzer = await analyzer.probe(session.privacy);
          publish('privacy.changed', session);
          return json(res, 200, { ...session, warning: 'Cloud analysis requires explicit consent. The setting was reverted to metadata-only.' });
        }
        session.analyzer = await analyzer.probe(session.privacy);
        return json(res, 200, publish('privacy.changed', session));
      }
      case 'voice': {
        const patch = parse(VoiceSettingsSchema, body);
        for (const [k, v] of Object.entries(patch)) if (v !== null && v !== undefined) session.voice[k] = v;
        if (patch.enabled === false) session.coach = { ...session.coach, muteUntil: null };
        return json(res, 200, publish('voice.changed', session));
      }
      case 'mute': {
        const minutes = Math.min(Math.max(Number(body.minutes) || 15, 1), 1440);
        session.coach = { ...session.coach, muteUntil: new Date(Date.now() + minutes * 60000).toISOString() };
        Session.appendEvent(session, { type: 'intervention.muted', minutes, until: session.coach.muteUntil });
        return json(res, 200, publish('voice.changed', session, { mutedUntil: session.coach.muteUntil }));
      }
      case 'unmute': {
        session.coach = { ...session.coach, muteUntil: null };
        return json(res, 200, publish('voice.changed', session));
      }
      case 'outcome':
        return json(res, 200, publish('report.updated', session, { event: Session.setOutcome(session, body.outcome) }));
      case 'interventions': {
        const intervention = session.interventions.find((i) => i.id === sub);
        if (!intervention) throw Object.assign(new Error('Intervention not found'), { status: 404 });
        if (body.action === 'dismiss') {
          coach.dismiss(intervention, body.note || 'Dismissed from the dashboard.');
          Session.appendEvent(session, { type: 'intervention.dismissed', interventionId: intervention.id });
        } else {
          throw Object.assign(new Error('Unknown intervention action'), { status: 400 });
        }
        return json(res, 200, publish('intervention.updated', session, { intervention }));
      }
      case 'recompute': {
        session.metrics = computeMetrics(session);
        return json(res, 200, publish('metrics.updated', session));
      }
      default:
        return json(res, 404, { error: `Unknown session action "${action}"` });
    }
  }

  return {
    server,
    listen(port, host) {
      const bindHost = host || process.env.FLOW_HOST || '127.0.0.1';
      const isLocal = bindHost === '127.0.0.1' || bindHost === 'localhost' || bindHost === '::1';
      if (!isLocal && !(allowRemote && remoteToken)) {
        throw new Error(
          `Refusing to bind to ${bindHost}: the FLOW API is unauthenticated. To expose it deliberately set both FLOW_ALLOW_REMOTE=1 and FLOW_AUTH_TOKEN=<secret>.`,
        );
      }
      return new Promise((resolve) => server.listen(port, bindHost, () => resolve(server.address())));
    },
    close() {
      hub.closeAll();
      return new Promise((resolve) => server.close(resolve));
    },
    staticRoot,
  };
}

export { randomUUID };
