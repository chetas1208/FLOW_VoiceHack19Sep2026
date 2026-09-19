/**
 * The observation pipeline.
 *
 *   OS Observer → Privacy Filter → Observation Processor → Semantic Analyzer
 *   → Temporal Reasoning → Session State → UI + Voice Coach
 *
 * One tick per live, capture-enabled session. Analysis is serialised per session
 * so a slow model can never overlap itself, and a tick is skipped rather than
 * queued if the previous one is still running — the dashboard stays responsive
 * and the coach keeps its timing even when inference is slow.
 */
import { applyPrivacyFilter } from './privacy.js';
import { captureScreenshot, checkPermissions, readFrontmost, isMac } from './macos.js';
import { recordObservation, isDuplicateObservation, appendEvent, now } from '../domain/session.js';
import { computeMetrics } from '../temporal/metrics.js';

export function createObservationRuntime({ store, analyzer, coach, hub, settings }) {
  /** Sessions with a tick in flight. */
  const inFlight = new Set();
  let permissionCache = null;
  let permissionCheckedAt = 0;

  async function permissions() {
    if (permissionCache && Date.now() - permissionCheckedAt < 30000) return permissionCache;
    permissionCache = await checkPermissions();
    permissionCheckedAt = Date.now();
    return permissionCache;
  }

  function publish(type, session, extra = {}) {
    store.set(session);
    hub.broadcast({ type, sessionId: session.id, session, ...extra });
  }

  /**
   * Run the full pipeline for one observation. Shared by the live observer, the
   * manual API route and the demo script, so every path gets identical
   * privacy filtering, analysis, memory and coaching.
   */
  async function ingest(session, raw, { allowWhilePaused = false } = {}) {
    if (session.status !== 'live' && !allowWhilePaused) {
      throw Object.assign(new Error('Session is not live'), { status: 409 });
    }

    // 1. Privacy filter — before anything is stored or sent to a model.
    const filtered = applyPrivacyFilter(session.privacy, { ...raw, time: raw.time || now() });
    if (!filtered.allowed) {
      return { excluded: true, reason: filtered.reason };
    }
    const observation = { ...filtered.observation, time: filtered.observation.time || now() };

    // 2. Duplicate suppression.
    if (isDuplicateObservation(session, observation)) {
      return { duplicate: true };
    }

    // 3. Semantic analysis (schema-validated, retention enforced inside).
    const { classification, meta } = await analyzer.analyze({
      goal: session.goal,
      observation,
      memory: session.memory,
      privacy: session.privacy,
    });

    // 4. Session state + temporal reasoning.
    const event = recordObservation(session, { observation, classification, meta });
    session.analyzer = analyzer.status;

    // 5. Coach.
    const verdict = coach.evaluate(session, event);
    const transition = verdict.transition;
    session.coach = verdict.coach;

    publish('observation.created', session, { event });
    if (transition) hub.broadcast({ type: 'drift.changed', sessionId: session.id, transition, coach: session.coach });

    let intervention = null;
    if (verdict.intervention) {
      intervention = verdict.intervention;
      session.interventions.push(intervention);
      appendEvent(session, { type: 'intervention.triggered', interventionId: intervention.id, transcript: intervention.transcript, reason: intervention.reason });
      coach.queue(intervention);
      publish('intervention.triggered', session, { intervention });
      // Speak out of band: voice latency must never block observation or the UI.
      coach.deliver(intervention, session).then(() => {
        session.metrics = computeMetrics(session);
        publish('intervention.updated', session, { intervention });
      });
    }

    return { event, intervention, classification, meta };
  }

  /** One observation tick for a single session. */
  async function tick(session) {
    if (inFlight.has(session.id)) return;
    inFlight.add(session.id);
    try {
      const perms = await permissions();
      if (session.capture.permission !== perms.accessibility) {
        session.capture.permission = perms.accessibility;
      }

      let frontmost;
      try {
        frontmost = await readFrontmost();
      } catch (err) {
        // Observation is genuinely unavailable. Say so once and stop capturing.
        session.capture.enabled = false;
        session.capture.status = 'unavailable';
        session.capture.lastError =
          err.code === 'UNSUPPORTED_PLATFORM'
            ? `Screen observation requires macOS. This server is running on ${process.platform}; use manual or simulated observations.`
            : `Could not read the frontmost application. ${perms.detail || err.message}`;
        publish('observer.status', session);
        return;
      }

      let screenshotPath = null;
      if (session.privacy.screenshotsEnabled) {
        if (perms.screenRecording !== 'granted') {
          if (session.capture.lastError !== 'screen-recording-denied') {
            session.capture.lastError = 'screen-recording-denied';
            session.capture.screenshots = false;
            hub.broadcast({
              type: 'observer.status',
              sessionId: session.id,
              detail: 'Screenshot capture is enabled for this session but macOS Screen Recording permission has not been granted. Analysis is continuing with window metadata only.',
            });
          }
        } else {
          const shot = await captureScreenshot({ excludedApps: session.privacy.excludedApps });
          if (shot.ok) {
            screenshotPath = shot.path;
            session.capture.lastCaptureAt = now();
            session.capture.screenshots = true;
          } else {
            session.capture.lastError = shot.error;
          }
        }
      }

      session.capture.status = 'observing';
      session.capture.lastError = session.capture.lastError === 'screen-recording-denied' ? session.capture.lastError : null;

      await ingest(session, {
        app: frontmost.app,
        title: frontmost.titleAvailable ? frontmost.title : '',
        screenshotPath,
        time: now(),
      });
    } catch (err) {
      session.capture.lastError = String(err.message).slice(0, 220);
      publish('observer.status', session);
    } finally {
      inFlight.delete(session.id);
    }
  }

  let timer = null;

  return {
    ingest,
    permissions,
    invalidatePermissions() {
      permissionCache = null;
    },

    start() {
      const interval = settings.get().observer.intervalMs || 5000;
      timer = setInterval(() => {
        for (const session of store.all()) {
          if (session.status !== 'live' || !session.capture.enabled) continue;
          if (session.mode === 'simulated') continue; // demo sessions are driven externally
          void tick(session);
        }
      }, interval);
      timer.unref?.();
      return this;
    },

    stop() {
      if (timer) clearInterval(timer);
      timer = null;
    },

    /** Recompute metrics for live sessions so elapsed unobserved time is reflected. */
    refreshLiveMetrics() {
      for (const session of store.all()) {
        if (session.status !== 'live') continue;
        session.metrics = computeMetrics(session);
        hub.broadcast({ type: 'metrics.updated', sessionId: session.id, metrics: session.metrics });
      }
    },

    isMac,
  };
}
