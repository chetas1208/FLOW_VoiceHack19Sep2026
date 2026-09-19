/**
 * Coach orchestration: runs the state machine, then owns the full lifecycle of
 * an intervention from `triggered` through to `speech_completed` / `failed`.
 *
 * Speech is queued and serialised — the coach never talks over itself — and a
 * mute arriving mid-queue cancels delivery rather than merely lowering volume.
 */
import { randomUUID } from 'node:crypto';
import { step, composeMessage, blankCoach, DEFAULTS } from './state-machine.js';
import { createMacSayProvider, createSilentProvider, VOICE_PROVIDERS } from './voice.js';

export { blankCoach, DEFAULTS, step, composeMessage };

export function createCoach({ provider = process.env.FLOW_VOICE_PROVIDER || 'macos-say', onEvent } = {}) {
  const factory = VOICE_PROVIDERS[provider] || createMacSayProvider;
  const voice = factory();
  let queue = Promise.resolve();

  const emit = (intervention, stage, extra = {}) => {
    const event = { ...extra, id: randomUUID(), type: `intervention.${stage}`, time: new Date().toISOString(), interventionId: intervention.id };
    intervention.lifecycle.push({ stage, at: event.time, ...extra });
    intervention.stage = stage;
    onEvent?.(event, intervention);
    return event;
  };

  return {
    voiceProviderName: voice.name,
    describeVoice: () => voice.describe(),
    async voiceAvailable() {
      return voice.available();
    },
    async listVoices() {
      return voice.listVoices ? voice.listVoices() : [];
    },

    /**
     * Feed the newest observation to the state machine.
     * @returns {{coach, transition, intervention: object|null}}
     */
    evaluate(session, observationEvent) {
      const settings = { ...DEFAULTS, ...(session.voice || {}) };
      const previous = session.events.filter((e) => e.type === 'observation.created').at(-2);
      const result = step(session.coach || blankCoach(session.startedAt), {
        category: observationEvent.category,
        confidence: observationEvent.confidence,
        time: observationEvent.time,
        appChanged: !!previous && previous.app !== observationEvent.app,
        voiceEnabled: !!session.voice?.enabled,
        settings,
      });

      let intervention = null;
      if (result.intervene) {
        const awayMs = new Date(observationEvent.time) - new Date(result.coach.driftSince || observationEvent.time);
        const lastAligned = [...session.events]
          .reverse()
          .find((e) => e.type === 'observation.created' && ['core', 'supporting', 'recovery'].includes(e.category));
        intervention = {
          id: randomUUID(),
          sessionId: session.id,
          triggeredAt: observationEvent.time,
          stage: 'triggered',
          transcript: composeMessage({
            goal: session.goal,
            awayMinutes: awayMs / 60000,
            lastAlignedContext: lastAligned?.taskContext || (lastAligned?.title ? `"${lastAligned.title}"` : null),
          }),
          reason: result.reason,
          observationId: observationEvent.id,
          evidence: observationEvent.evidence || [],
          driftStartedAt: result.coach.driftSince,
          driftSeconds: Math.round(awayMs / 1000),
          confidence: observationEvent.confidence,
          coachStateBefore: session.coach?.state ?? 'FOCUSED',
          dismissed: false,
          lifecycle: [{ stage: 'triggered', at: observationEvent.time }],
          outcome: null,
        };
      }
      return { coach: result.coach, transition: result.transition, intervention };
    },

    /**
     * Speak an intervention. Resolves once delivery has settled so callers can
     * await completion in tests; in the server this is fire-and-forget.
     */
    deliver(intervention, session) {
      const run = async () => {
        const mutedUntil = session.coach?.muteUntil;
        if (intervention.dismissed) return emit(intervention, 'dismissed', { note: 'Dismissed before delivery.' });
        if (mutedUntil && Date.now() < new Date(mutedUntil).getTime()) {
          return emit(intervention, 'muted', { note: `Muted until ${mutedUntil}; not spoken.` });
        }
        if (!session.voice?.enabled) {
          return emit(intervention, 'muted', { note: 'Voice was disabled before delivery.' });
        }
        const check = await voice.available();
        if (!check.ok) return emit(intervention, 'failed', { error: check.reason });

        emit(intervention, 'speech_started', { provider: voice.name });
        const started = Date.now();
        const res = await voice.speak(intervention.transcript, { voice: session.voice?.voice, rate: session.voice?.rate });
        if (!res.ok) return emit(intervention, 'failed', { error: res.error || 'speech-failed', provider: voice.name });
        return emit(intervention, 'speech_completed', { provider: voice.name, durationMs: Date.now() - started, silent: !!res.silent });
      };
      queue = queue.then(run, run);
      return queue;
    },

    /** Mark queued so the UI can show the pill before audio begins. */
    queue(intervention) {
      return emit(intervention, 'queued');
    },
    dismiss(intervention, note = 'Dismissed by the user.') {
      intervention.dismissed = true;
      return emit(intervention, 'dismissed', { note });
    },
    mute(intervention, until) {
      return emit(intervention, 'muted', { note: `Muted until ${until}.` });
    },
  };
}

/**
 * Compare activity in the window before and after an intervention.
 *
 * This is a temporal association, not causal evidence, and the returned object
 * says so explicitly — a user may have returned to work for reasons that have
 * nothing to do with the coach.
 */
export function analyseInterventionOutcome(intervention, intervals, windowMinutes = 4) {
  const t = new Date(intervention.triggeredAt).getTime();
  const w = windowMinutes * 60000;

  const share = (from, to) => {
    let aligned = 0;
    let away = 0;
    let unknown = 0;
    let total = 0;
    for (const i of intervals) {
      const s = new Date(i.startedAt).getTime();
      const e = new Date(i.endedAt).getTime();
      const overlap = Math.max(0, Math.min(e, to) - Math.max(s, from));
      if (overlap <= 0) continue;
      total += overlap;
      if (['core', 'supporting', 'recovery'].includes(i.category)) aligned += overlap;
      else if (['drift', 'distraction'].includes(i.category)) away += overlap;
      else unknown += overlap;
    }
    return {
      windowMs: to - from,
      observedMs: total,
      alignedMs: aligned,
      awayMs: away,
      unknownMs: unknown,
      alignedShare: total > 0 ? Math.round((aligned / total) * 100) : null,
    };
  };

  const before = share(t - w, t);
  const after = share(t, t + w);
  const delta = before.alignedShare === null || after.alignedShare === null ? null : after.alignedShare - before.alignedShare;

  return {
    interventionId: intervention.id,
    windowMinutes,
    before,
    after,
    alignedShareDelta: delta,
    returnedToGoal: after.alignedMs > 0 && after.alignedShare >= 50,
    observation:
      delta === null
        ? 'Not enough observed time on one side of the intervention to compare.'
        : delta > 0
          ? `Goal-aligned share was ${delta} points higher in the ${windowMinutes} minutes after this intervention than in the ${windowMinutes} minutes before.`
          : delta < 0
            ? `Goal-aligned share was ${Math.abs(delta)} points lower after this intervention than before.`
            : 'Goal-aligned share was unchanged either side of this intervention.',
    caveat:
      'This is a temporal association between an intervention and subsequent activity. It is not evidence that the intervention caused the change — no control condition exists, the sample is one session, and the user may have returned for unrelated reasons.',
  };
}
