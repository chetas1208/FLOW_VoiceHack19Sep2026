import { Navigate } from 'react-router-dom';

/** Legacy /docs URL — Docs lives as the third tab inside /app. */
export function DocsPage() {
  return <Navigate to="/app?tab=docs" replace />;
}
