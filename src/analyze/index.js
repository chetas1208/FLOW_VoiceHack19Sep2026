/**
 * Semantic analyzer orchestrator.
 *
 * Responsibilities:
 *   - pick a provider that is actually available, honouring the session's
 *     privacy settings (cloud requires explicit consent);
 *   - validate every model output against the shared schema before it is
 *     allowed anywhere near the session state;
 *   - degrade honestly — if inference fails we fall back to clearly-labelled
 *     metadata-only analysis (or report unavailable), never to a fabricated score;
 *   - enforce screenshot retention immediately after analysis.
 */
import { validateClassification, validateAnalysisMeta } from '../domain/contracts.js';
import { discardScreenshot, mayUseCloud } from '../observe/privacy.js';
import { memoryForPrompt } from './memory.js';
import { createHeuristicProvider } from './providers/heuristic.js';
import { createOllamaProvider } from './providers/ollama.js';
import { createAnthropicProvider } from './providers/anthropic.js';

export const PROVIDERS = {
  heuristic: createHeuristicProvider,
  ollama: createOllamaProvider,
  anthropic: createAnthropicProvider,
};

/** Order tried when the configured provider is unavailable. Local before cloud. */
const FALLBACK_ORDER = ['ollama', 'anthropic', 'heuristic'];

export function createAnalyzer({ provider = process.env.FLOW_ANALYZER || 'auto', onStatus } = {}) {
  const instances = new Map();
  let status = { provider: null, state: 'unknown', detail: 'Analyzer has not been probed yet.', checkedAt: null };

  const instance = (name) => {
    if (!instances.has(name)) instances.set(name, PROVIDERS[name]());
    return instances.get(name);
  };

  const setStatus = (next) => {
    status = { ...next, checkedAt: new Date().toISOString() };
    onStatus?.(status);
    return status;
  };

  /** Resolve which provider to use for a given privacy configuration. */
  async function resolve(privacy) {
    const wanted = provider === 'auto' ? null : provider;
    const cloudAllowed = mayUseCloud(privacy);
    const analysisLocation = privacy?.analysisLocation || 'metadata-only';

    if (analysisLocation === 'metadata-only') {
      return { provider: instance('heuristic'), reason: 'Privacy settings select metadata-only analysis.' };
    }

    const order = wanted ? [wanted, ...FALLBACK_ORDER.filter((n) => n !== wanted)] : FALLBACK_ORDER;
    const notes = [];
    for (const name of order) {
      if (!PROVIDERS[name]) continue;
      const p = instance(name);
      if (p.requiresConsent && !cloudAllowed) {
        notes.push(`${name}: skipped (cloud analysis not consented to)`);
        continue;
      }
      if (name !== 'heuristic' && analysisLocation === 'local' && p.requiresConsent) {
        notes.push(`${name}: skipped (privacy settings select local analysis)`);
        continue;
      }
      const check = await p.available();
      if (check.ok) return { provider: p, reason: notes.join('; ') || null };
      notes.push(`${name}: ${check.reason}`);
    }
    return { provider: instance('heuristic'), reason: notes.join('; ') };
  }

  return {
    get status() {
      return status;
    },

    /** Probe providers and publish a status without classifying anything. */
    async probe(privacy) {
      const { provider: p, reason } = await resolve(privacy);
      return setStatus({
        provider: p.name,
        model: p.model || null,
        modality: p.modality,
        state: p.name === 'heuristic' && (privacy?.analysisLocation || 'metadata-only') !== 'metadata-only' ? 'degraded' : 'ready',
        detail: p.describe(),
        note: reason || null,
      });
    },

    /**
     * Classify one privacy-filtered observation.
     * @returns {Promise<{classification: object, meta: object}>}
     */
    async analyze({ goal, observation, memory, privacy }) {
      const { provider: chosen, reason } = await resolve(privacy);
      const recent = memory?.recent || [];
      const promptMemory = memoryForPrompt(memory);
      const retention = privacy?.retention === 'retain' ? 'retained' : 'discard-after-analysis';

      let result = null;
      let degraded = false;
      let note = reason || null;
      let used = chosen;

      try {
        result = await chosen.classify({ goal, observation, memory: promptMemory, recent });
      } catch (err) {
        // Inference failed at call time. Fall back to the heuristic, clearly labelled.
        degraded = true;
        note = `${chosen.name} failed: ${String(err.message).slice(0, 180)}. Fell back to metadata-only analysis.`;
        used = instance('heuristic');
        setStatus({ provider: chosen.name, model: chosen.model || null, modality: chosen.modality, state: 'degraded', detail: note });
        result = await used.classify({ goal, observation, memory: promptMemory, recent });
      }

      let classification;
      try {
        classification = validateClassification(result.classification);
      } catch (err) {
        // A model returned something off-contract. Do not guess what it meant.
        degraded = true;
        note = `${used.name} returned an output that failed schema validation (${String(err.message).slice(0, 140)}). Recorded as unknown.`;
        classification = validateClassification({
          category: 'unknown',
          goalRelevance: null,
          confidence: 0,
          evidence: [`Active application: ${observation.app}`],
          explanation: 'The analyzer returned a malformed result, so this interval is recorded as unknown rather than guessed.',
        });
      }

      const meta = validateAnalysisMeta({
        provider: used.name,
        model: result.model || used.model || null,
        modality: result.modality || used.modality,
        latencyMs: result.latencyMs ?? null,
        usedScreenshot: !!result.usedScreenshot,
        screenshotRetention: !observation.screenshotPath ? 'not-captured' : retention === 'retained' ? 'retained' : 'discarded-after-analysis',
        degraded,
        note,
      });

      // Retention is enforced here, immediately after the model has seen the image.
      if (observation.screenshotPath && retention !== 'retained') discardScreenshot(observation.screenshotPath);

      if (!degraded) {
        setStatus({ provider: used.name, model: meta.model, modality: meta.modality, state: 'ready', detail: used.describe(), note: reason || null });
      }

      return { classification, meta };
    },
  };
}
