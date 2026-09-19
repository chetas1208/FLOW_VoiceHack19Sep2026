import { useSyncExternalStore } from 'react';
import { auth } from './auth';

let snapshot = { status: auth.status(), email: auth.email(), notice: auth.notice(), v: 0 };
auth.subscribe(() => { snapshot = { status: auth.status(), email: auth.email(), notice: auth.notice(), v: snapshot.v + 1 }; });

export function useAuth() {
  return useSyncExternalStore(auth.subscribe, () => snapshot);
}
