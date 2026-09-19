import { Link } from 'react-router-dom';
import { EmptyState } from '../components/primitives';
import { useDocumentTitle } from '../lib/hooks';

export function NotFoundPage() {
  useDocumentTitle('Not found');
  return <EmptyState title="That page does not exist" action={<Link className="btn btn-secondary" to="/sessions">Go to sessions</Link>}>The link may be old, or the session may belong to another account.</EmptyState>;
}
