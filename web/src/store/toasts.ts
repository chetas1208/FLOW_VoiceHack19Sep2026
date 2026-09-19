import { useSyncExternalStore } from 'react';

export interface Toast { id: number; tone: 'info' | 'ok' | 'error'; text: string }
let toasts: Toast[] = [];
let n = 0;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export function toast(text: string, tone: Toast['tone'] = 'info', ms = 6000) {
  const id = ++n;
  toasts = [...toasts.slice(-3), { id, tone, text }];
  emit();
  setTimeout(() => dismissToast(id), ms);
}
export function dismissToast(id: number) { toasts = toasts.filter((t) => t.id !== id); emit(); }
export function useToasts(): Toast[] {
  return useSyncExternalStore((l) => { listeners.add(l); return () => { listeners.delete(l); }; }, () => toasts);
}
