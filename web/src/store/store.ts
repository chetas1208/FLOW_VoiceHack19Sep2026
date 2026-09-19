import { useSyncExternalStore } from 'react';
import { Action, AppState, initialState, reducer } from './reducer';

type Listener = () => void;

/** Minimal external store so non-React code (WebSocket callbacks) can dispatch. */
export function createStore(initial: AppState = initialState) {
  let state = initial;
  const listeners = new Set<Listener>();
  return {
    getState: () => state,
    dispatch(action: Action) {
      const next = reducer(state, action);
      if (next === state) return;
      state = next;
      listeners.forEach((l) => l());
    },
    subscribe(l: Listener) { listeners.add(l); return () => { listeners.delete(l); }; },
  };
}

export type Store = ReturnType<typeof createStore>;
export const store = createStore();

export function useStore<T>(selector: (s: AppState) => T): T {
  return useSyncExternalStore(store.subscribe, () => selector(store.getState()));
}
