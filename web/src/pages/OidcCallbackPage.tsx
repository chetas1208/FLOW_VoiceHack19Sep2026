import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { auth } from '../auth/auth';
import { completeLogin } from '../auth/oidc';
import { Spinner } from '../components/primitives';

export function OidcCallbackPage() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const ran = useRef(false);
  useEffect(() => {
    if (ran.current) return; // the transaction is single use; StrictMode would run this twice
    ran.current = true;
    completeLogin(window.location.search)
      .then(({ credentials, returnTo }) => {
        auth.setCredentials(credentials);
        navigate(returnTo, { replace: true });
      })
      .catch((e: Error) => setError(e.message));
  }, [navigate]);
  return (
    <div className="center-page">
      {error ? (
        <div className="panel narrow">
          <h1>Sign-in did not finish</h1>
          <p className="banner banner-bad" role="alert">{error}</p>
          <Link className="btn btn-primary" to="/login">Back to sign in</Link>
        </div>
      ) : <Spinner label="Finishing sign-in" />}
    </div>
  );
}
