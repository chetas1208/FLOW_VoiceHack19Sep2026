/**
 * Voice delivery providers behind one interface, so a cloud TTS can be added
 * later without touching the state machine.
 */
import { speak as macSpeak, listVoices, isMac } from '../observe/macos.js';

export function createMacSayProvider() {
  return {
    name: 'macos-say',
    describe: () => 'macOS built-in speech synthesis (`say`). Runs entirely on-device; no audio leaves the machine.',
    async available() {
      return isMac ? { ok: true } : { ok: false, reason: `The macOS speech synthesizer is not available on ${process.platform}.` };
    },
    listVoices,
    async speak(text, options) {
      return macSpeak(text, options);
    },
  };
}

/** Records what would have been spoken. Used by tests and the deterministic demo. */
export function createSilentProvider(sink = []) {
  return {
    name: 'silent',
    describe: () => 'Silent provider: interventions are recorded but never spoken aloud.',
    async available() {
      return { ok: true };
    },
    async listVoices() {
      return [];
    },
    async speak(text) {
      sink.push({ text, at: new Date().toISOString() });
      return { ok: true, silent: true };
    },
    get spoken() {
      return sink;
    },
  };
}

export const VOICE_PROVIDERS = { 'macos-say': createMacSayProvider, silent: createSilentProvider };
