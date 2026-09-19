# Web contract

The future Vercel application consumes the versioned cloud boundary, not the
local observer. Current local-compatible routes include `POST /v1/sessions`,
`GET /v1/sessions/{id}`, `POST /v1/sessions/{id}/observations`, and
`POST /v1/sessions/{id}/stop`. The existing local `/flow/*` routes remain for
development compatibility. Authentication UX, account management, device
revocation, and live dashboard UI are not implemented here.
