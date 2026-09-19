/**
 * Global defaults applied to new sessions, persisted next to the session data.
 * Nothing secret is stored here — API credentials stay in the environment.
 */
import fs from 'node:fs';
import path from 'node:path';
import { defaultPrivacySettings } from '../observe/privacy.js';
import { DEFAULTS as COACH_DEFAULTS } from '../coach/state-machine.js';

export function defaultSettings() {
  return {
    privacy: defaultPrivacySettings(),
    voice: { enabled: false, voice: null, rate: 185, ...COACH_DEFAULTS },
    observer: { intervalMs: 5000 },
    analyzer: { provider: process.env.FLOW_ANALYZER || 'auto' },
  };
}

export function createSettingsStore({ file }) {
  let current = defaultSettings();
  try {
    const raw = JSON.parse(fs.readFileSync(file, 'utf8'));
    current = {
      ...current,
      ...raw,
      privacy: { ...current.privacy, ...(raw.privacy || {}) },
      voice: { ...current.voice, ...(raw.voice || {}) },
      observer: { ...current.observer, ...(raw.observer || {}) },
      analyzer: { ...current.analyzer, ...(raw.analyzer || {}) },
    };
  } catch (err) {
    if (err.code !== 'ENOENT') console.error('[flow] could not read settings:', err.message);
  }

  function save() {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const tmp = `${file}.${process.pid}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(current, null, 2), { mode: 0o600 });
    fs.renameSync(tmp, file);
  }

  return {
    get: () => current,
    update(patch) {
      current = {
        ...current,
        ...patch,
        privacy: { ...current.privacy, ...(patch.privacy || {}) },
        voice: { ...current.voice, ...(patch.voice || {}) },
        observer: { ...current.observer, ...(patch.observer || {}) },
        analyzer: { ...current.analyzer, ...(patch.analyzer || {}) },
      };
      save();
      return current;
    },
    reset() {
      current = defaultSettings();
      save();
      return current;
    },
  };
}
