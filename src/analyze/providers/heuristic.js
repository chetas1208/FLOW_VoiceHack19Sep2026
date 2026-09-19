/**
 * Metadata-only heuristic provider.
 *
 * This is the honest floor of the system: no model, no screenshot, just the app
 * name and window title matched against the goal. It is always available, and
 * everything it produces is labelled `modality: 'metadata-only'` so the UI can
 * say plainly that no semantic understanding took place.
 *
 * It is intentionally conservative — it prefers `unknown` to a confident guess.
 */
import { ALIGNED_CATEGORIES } from '../../domain/contracts.js';

const STOPWORDS = new Set(
  'the and get fix with from into that this for app work make take also але use using our your out new all any can via then than when what which while into onto about'.split(' '),
);

const DEV_APPS = /visual studio|vs ?code|cursor|zed|sublime|intellij|pycharm|webstorm|goland|xcode|android studio|terminal|iterm|warp|ghostty|alacritty|kitty|nvim|vim|emacs|fork|sourcetree|tower|docker|postman|insomnia|tableplus|dbeaver/i;
const DOC_HINTS = /\bdocs?\b|documentation|\brfc\b|reference|api reference|manual|guide|tutorial|specification|\bmdn\b|stack overflow|stackoverflow|github|gitlab|readme|changelog|man page/i;
const COMMS_APPS = /slack|discord|teams|zoom|meet|gmail|outlook|linear|jira|notion|asana|basecamp|height/i;
const RECREATION = /youtube|netflix|twitch|reddit|instagram|tiktok|facebook|\bx\.com\b|twitter|pinterest|9gag|hulu|disney\+|prime video|spotify|steam|epic games|amazon\.|ebay|aliexpress|shopping cart/i;

/** Goal terms worth matching on: length-filtered, stopword-filtered, deduped. */
export function goalTerms(goal) {
  const raw = String(goal || '').toLowerCase().match(/[a-z0-9][a-z0-9+#._-]{2,}/g) || [];
  return [...new Set(raw.filter((t) => !STOPWORDS.has(t) && t.length >= 3))];
}

/** Count how many goal terms appear in the observed text, with a light stem match. */
export function matchTerms(terms, text) {
  const hay = String(text || '').toLowerCase();
  return terms.filter((t) => {
    if (hay.includes(t)) return true;
    // Tolerate simple plural/verb endings: "test" matches "tests", "testing".
    const stem = t.replace(/(ing|ed|es|s)$/, '');
    return stem.length >= 4 && hay.includes(stem);
  });
}

export function createHeuristicProvider() {
  return {
    name: 'heuristic',
    modality: 'metadata-only',
    describe: () => 'Keyword overlap between the session goal and the window title. No semantic understanding.',
    async available() {
      return { ok: true };
    },
    async classify({ goal, observation, memory }) {
      const started = Date.now();
      const app = observation.app || '';
      const title = observation.title || '';
      const haystack = `${app} ${title}`;
      const terms = goalTerms(goal);
      const hits = matchTerms(terms, haystack);
      const isDev = DEV_APPS.test(app);
      const isDoc = DOC_HINTS.test(haystack);
      const isComms = COMMS_APPS.test(app);
      const isRecreation = RECREATION.test(haystack);
      const wasAway = !!memory?.lastAwayAt;

      const evidence = [`Active application: ${app}`];
      if (observation.titleWithheld) evidence.push('Window title withheld (private context)');
      else if (title) evidence.push(`Window title: "${title}"`);
      else evidence.push('Window title: empty');
      if (hits.length) evidence.push(`Goal terms present in the title: ${hits.join(', ')}`);

      const decide = (category, goalRelevance, confidence, explanation) => {
        const recovered = wasAway && ALIGNED_CATEGORIES.includes(category) && category !== 'recovery';
        return {
          classification: {
            category: recovered ? 'recovery' : category,
            goalRelevance,
            confidence,
            confidenceCalibrated: false,
            evidence,
            explanation: recovered ? `${explanation} This follows a period away from the goal, so it is recorded as recovery.` : explanation,
            taskContext: hits.length ? hits.slice(0, 2).join(' ') : isDev ? `${app} (unmatched)` : app,
            progressSignal: null,
          },
          latencyMs: Date.now() - started,
        };
      };

      if (observation.titleWithheld) {
        return decide('unknown', null, 0.15, 'The window title was withheld for privacy, so no relevance judgement is possible.');
      }
      // Recreation only beats a goal match when the goal itself is unrelated to it.
      if (isRecreation && hits.length === 0) {
        return decide('distraction', 0.05, 0.7, 'The title matches a commonly recreational destination and contains no goal terms. Keyword matching cannot see page content, so this may be a false positive.');
      }
      if (hits.length && isDev) {
        return decide('core', Math.min(0.95, 0.7 + hits.length * 0.08), Math.min(0.8, 0.5 + hits.length * 0.1), `A development application is active and the window title contains ${hits.length} goal term(s).`);
      }
      if (hits.length && (isDoc || isComms || !isDev)) {
        return decide('supporting', Math.min(0.9, 0.6 + hits.length * 0.08), Math.min(0.75, 0.45 + hits.length * 0.1), `The window title contains ${hits.length} goal term(s) outside a development app, which suggests supporting research or discussion.`);
      }
      if (isDev) {
        return decide('unknown', null, 0.3, 'A development application is active, but nothing in the title establishes a link to the stated goal.');
      }
      if (isRecreation) {
        return decide('drift', 0.2, 0.4, 'The title matches a commonly recreational destination but also contains goal terms, so it may be legitimate research.');
      }
      return decide('unknown', null, 0.2, 'There is not enough metadata to judge whether this activity supports the goal.');
    },
  };
}
