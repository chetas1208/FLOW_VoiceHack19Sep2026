/**
 * Local vision-language provider via Ollama.
 *
 * Preferred when available: screen content never leaves the machine, so it needs
 * no cloud-consent gate. Works with a text model (metadata only) or a vision
 * model (screenshot understanding) — the modality reported downstream reflects
 * what actually happened, not what was configured.
 */
import fs from 'node:fs/promises';
import { SYSTEM_PROMPT, buildUserPrompt, CLASSIFICATION_JSON_SCHEMA } from '../prompt.js';

const DEFAULT_HOST = process.env.FLOW_OLLAMA_HOST || 'http://127.0.0.1:11434';
const DEFAULT_MODEL = process.env.FLOW_OLLAMA_MODEL || 'qwen2.5vl:7b';
/** Models that can actually read an image. Anything else gets metadata only. */
const VISION_MODELS = /llava|bakllava|moondream|minicpm-v|qwen2\.?5?vl|qwen3-?vl|llama3\.2-vision|gemma3|mistral-small3|granite3\.2-vision/i;

export function createOllamaProvider({ host = DEFAULT_HOST, model = DEFAULT_MODEL } = {}) {
  const supportsVision = VISION_MODELS.test(model);

  return {
    name: 'ollama',
    modality: supportsVision ? 'vision-language' : 'text-language',
    model,
    describe: () => `Local ${supportsVision ? 'vision-language' : 'text'} model "${model}" served by Ollama at ${host}. Screen content stays on this machine.`,

    async available() {
      try {
        const res = await fetch(`${host}/api/tags`, { signal: AbortSignal.timeout(2500) });
        if (!res.ok) return { ok: false, reason: `Ollama responded ${res.status}` };
        const body = await res.json();
        const names = (body.models || []).map((m) => m.name);
        if (!names.length) return { ok: false, reason: 'Ollama is running but has no models installed. Try: ollama pull ' + model };
        const installed = names.some((n) => n === model || n.split(':')[0] === model.split(':')[0]);
        if (!installed) return { ok: false, reason: `Model "${model}" is not installed. Try: ollama pull ${model}` };
        return { ok: true, models: names };
      } catch (err) {
        return { ok: false, reason: `Ollama is not reachable at ${host} (${String(err.message).slice(0, 80)})` };
      }
    },

    async classify({ goal, observation, memory, recent, signal }) {
      const started = Date.now();
      const images = [];
      let usedScreenshot = false;
      if (supportsVision && observation.screenshotPath) {
        try {
          images.push((await fs.readFile(observation.screenshotPath)).toString('base64'));
          usedScreenshot = true;
        } catch {
          /* screenshot vanished (retention policy); continue on metadata */
        }
      }

      const res = await fetch(`${host}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: signal ?? AbortSignal.timeout(Number(process.env.FLOW_INFERENCE_TIMEOUT_MS || 30000)),
        body: JSON.stringify({
          model,
          stream: false,
          format: CLASSIFICATION_JSON_SCHEMA, // Ollama constrains decoding to this schema
          options: { temperature: 0.1, num_predict: 400 },
          messages: [
            { role: 'system', content: SYSTEM_PROMPT },
            { role: 'user', content: buildUserPrompt({ goal, observation, memory, recent }), ...(images.length ? { images } : {}) },
          ],
        }),
      });

      if (!res.ok) throw new Error(`Ollama returned ${res.status}: ${(await res.text()).slice(0, 200)}`);
      const body = await res.json();
      const text = body?.message?.content;
      if (!text) throw new Error('Ollama returned an empty message');

      let parsed;
      try {
        parsed = JSON.parse(text);
      } catch {
        // Some models wrap JSON in prose or fences despite the format constraint.
        const m = text.match(/\{[\s\S]*\}/);
        if (!m) throw new Error('Ollama did not return JSON');
        parsed = JSON.parse(m[0]);
      }

      return {
        classification: parsed,
        model,
        usedScreenshot,
        modality: usedScreenshot ? 'vision-language' : 'text-language',
        latencyMs: Date.now() - started,
      };
    },
  };
}
