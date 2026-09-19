import type { SVGProps } from 'react';

const P: Record<string, JSX.Element> = {
  play: <path d="M7 5.5v13l11-6.5z" />,
  pause: <><path d="M8 5.5v13" /><path d="M16 5.5v13" /></>,
  stop: <rect x="6.5" y="6.5" width="11" height="11" rx="2" />,
  mute: <><path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z" /><path d="M16 9l5 6M21 9l-5 6" /></>,
  volume: <><path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z" /><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a8 8 0 0 1 0 11" /></>,
  moon: <path d="M19 14.5A7.5 7.5 0 0 1 9.5 5 7.5 7.5 0 1 0 19 14.5z" />,
  target: <><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="4" /><circle cx="12" cy="12" r=".8" fill="currentColor" /></>,
  chat: <path d="M4.5 6.5a2 2 0 0 1 2-2h11a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H10l-4 3.5v-3.5h-.0a2 2 0 0 1-1.5-2z" />,
  agent: <><rect x="5" y="8" width="14" height="10" rx="3" /><path d="M12 8V5M9.5 12.5v1M14.5 12.5v1M9.5 16h5" /><circle cx="12" cy="4.2" r="1" /></>,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  x: <path d="M6 6l12 12M18 6L6 18" />,
  chevron: <path d="M7 9.5l5 5 5-5" />,
  shield: <path d="M12 3.5l7 2.5v5.5c0 4.3-3 7.6-7 9-4-1.4-7-4.7-7-9V6z" />,
  clock: <><circle cx="12" cy="12" r="8" /><path d="M12 7.5V12l3 2" /></>,
  bolt: <path d="M13 3.5L6 13h5l-1 7.5L18 11h-5z" />,
  up: <path d="M8 11V19H5V11zM8 11l3.2-6.3A1.7 1.7 0 0 1 14.5 6l-.7 4h4.4a1.8 1.8 0 0 1 1.8 2.1l-1 5.6a2 2 0 0 1-2 1.6H8" />,
  down: <path d="M8 13V5H5v8zM8 13l3.2 6.3a1.7 1.7 0 0 0 3.3-1.3l-.7-4h4.4a1.8 1.8 0 0 0 1.8-2.1l-1-5.6a2 2 0 0 0-2-1.6H8" />,
  device: <><rect x="4.5" y="5.5" width="15" height="10" rx="1.8" /><path d="M2.5 19h19" /></>,
  alert: <><path d="M12 4l9 15.5H3z" /><path d="M12 10v4M12 16.8v.2" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  refresh: <path d="M19 8a7.5 7.5 0 1 0 1 6M19 4v4h-4" />,
  user: <><circle cx="12" cy="8.5" r="3.5" /><path d="M5 19.5c1-3.5 3.7-5 7-5s6 1.5 7 5" /></>,
  logout: <><path d="M10 5H6.5A1.5 1.5 0 0 0 5 6.5v11A1.5 1.5 0 0 0 6.5 19H10" /><path d="M15 8l4 4-4 4M19 12H9.5" /></>,
  list: <path d="M8 6.5h11M8 12h11M8 17.5h11M4.5 6.5h.01M4.5 12h.01M4.5 17.5h.01" />,
  info: <><circle cx="12" cy="12" r="8.5" /><path d="M12 11v5M12 8v.2" /></>,
  down2: <path d="M12 5v14M6 13l6 6 6-6" />,
  send: <path d="M4 12l16-7-6 15-3-6z" />,
  lock: <><rect x="5.5" y="10.5" width="13" height="9" rx="2" /><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5" /></>,
  eye: <><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" /><circle cx="12" cy="12" r="2.8" /></>,
};

export type IconName = keyof typeof P;

export function Icon({ name, size = 18, ...rest }: { name: IconName; size?: number } & Omit<SVGProps<SVGSVGElement>, 'name'>) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" {...rest}>
      {P[name]}
    </svg>
  );
}
