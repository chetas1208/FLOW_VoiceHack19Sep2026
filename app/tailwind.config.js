import path from 'node:path';

const here = path.dirname(new URL(import.meta.url).pathname);

/** FLOW design tokens from the UI/UX spec §02. */
export default {
  // Absolute globs: PostCSS resolves this config relative to the process CWD,
  // which differs between `vite build` (repo root) and `vite dev` (app/).
  content: [path.join(here, 'index.html'), path.join(here, 'src/**/*.{ts,tsx}')],
  theme: {
    extend: {
      colors: {
        bg0: '#06080D',
        bg1: '#0A0D14',
        surface1: '#111827',
        surface2: '#151C2C',
        line: 'rgba(148,163,184,.16)',
        text1: '#F8FAFC',
        text2: '#A7B0C2',
        cyan: '#22D3EE',
        violet: '#8B5CF6',
        magenta: '#EC4899',
        lime: '#A3E635',
        amber: '#FBBF24',
        rose: '#FB7185',
        slate: '#64748B',
      },
      borderRadius: { card: '22px' },
      boxShadow: {
        float: '0 18px 60px rgba(0,0,0,.36)',
        edge: '0 0 0 1px rgba(34,211,238,.16), 0 0 32px rgba(139,92,246,.08)',
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', 'Inter', 'Segoe UI', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'SF Mono', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
};
