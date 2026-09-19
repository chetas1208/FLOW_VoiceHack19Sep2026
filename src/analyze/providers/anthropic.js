/**
 * Cloud vision-language provider via the Anthropic Messages API.
 *
 * Gated twice before it is ever reached: the session's privacy settings must
 * select `analysisLocation: 'cloud'` AND record explicit `cloudConsent`. The
 * orchestrator enforces that — this module simply refuses to run without a key.
 *
 * No credential is ever written to disk or into a session record.
 */
import fs from 'node:fs/promises';
import { SYSTEM_PROMPT, buildUserPrompt, CLASSIFICATION_JSON_SCHEMA } from '../prompt.js';

const DEFAULT_MODEL = process.env.FLOW_ANTHROPIC_MODEL || 'claude-opus-5';

/** Lazily loaded so FLOW runs fine when the SDK is absent. */
let AnthropicCtor = null;
async function loadSdk() {
  if (AnthropicCtor) return AnthropicCtor;
  const mod = await import('@anthropic-ai/sdk');
  AnthropicCtor = mod.default ?? mod.Anthropic;
  return AnthropicCtor;
}

export function createAnthropicProvider({ model = DEFAULT_MODEL } = {}) {
  let client = null;

  async function getClient() {
    if (client) return client;
    const Anthropic = await loadSdk();
    // Resolves ANTHROPIC_API_KEY (or an `ant auth login` profile) from the environment.
    client = new Anthropic();
    return client;
  }

  return {
    name: 'anthropic',
    modality: 'vision-language',
    model,
    requiresConsent: true,
    describe: () => `Anthropic ${model}. Screen metadata — and screenshots when enabled — are sent to Anthropic's API. Requires explicit consent.`,

    async available() {
      if (!process.env.ANTHROPIC_API_KEY && !process.env.ANTHROPIC_AUTH_TOKEN) {
        return { ok: false, reason: 'No ANTHROPIC_API_KEY in the environment. Copy .env.example to .env and set it, or run `ant auth login`.' };
      }
      try {
        await loadSdk();
      } catch {
        return { ok: false, reason: 'The @anthropic-ai/sdk package is not installed. Run: npm install @anthropic-ai/sdk' };
      }
      return { ok: true };
    },

    async classify({ goal, observation, memory, recent }) {
      const started = Date.now();
      const anthropic = await getClient();

      const content = [];
      let usedScreenshot = false;
      if (observation.screenshotPath) {
        try {
          const data = (await fs.readFile(observation.screenshotPath)).toString('base64');
          content.push({ type: 'image', source: { type: 'base64', media_type: 'image/jpeg', data } });
          usedScreenshot = true;
        } catch {
          /* screenshot already discarded; fall back to metadata */
        }
      }
      content.push({ type: 'text', text: buildUserPrompt({ goal, observation, memory, recent }) });

      const response = await anthropic.messages.create({
        model,
        max_tokens: 1024,
        system: SYSTEM_PROMPT,
        // Classification is a shallow task: low effort keeps this fast and cheap
        // enough to run every few seconds during a live session.
        output_config: {
          effort: 'low',
          format: { type: 'json_schema', schema: CLASSIFICATION_JSON_SCHEMA },
        },
        messages: [{ role: 'user', content }],
      });

      if (response.stop_reason === 'refusal') {
        throw new Error(`Model declined to classify this observation (${response.stop_details?.category ?? 'unspecified'}).`);
      }

      const text = response.content.filter((b) => b.type === 'text').map((b) => b.text).join('');
      if (!text.trim()) throw new Error('Anthropic returned an empty response');

      let parsed;
      try {
        parsed = JSON.parse(text);
      } catch {
        const m = text.match(/\{[\s\S]*\}/);
        if (!m) throw new Error('Anthropic did not return JSON');
        parsed = JSON.parse(m[0]);
      }

      return {
        classification: parsed,
        model,
        usedScreenshot,
        modality: usedScreenshot ? 'vision-language' : 'text-language',
        latencyMs: Date.now() - started,
        usage: response.usage ? { input: response.usage.input_tokens, output: response.usage.output_tokens } : null,
      };
    },
  };
}
