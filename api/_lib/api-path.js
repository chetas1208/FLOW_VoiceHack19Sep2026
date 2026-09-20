function segmentsFromPath(value) {
  if (Array.isArray(value)) return value.flatMap((part) => String(part).split('/')).filter(Boolean);
  if (typeof value === 'string' && value) return value.split('/').filter(Boolean);
  return [];
}

export function apiSegments(req) {
  const fromRewrite = segmentsFromPath(req.query?.path ?? req.query?.['...path']);
  if (fromRewrite.length) return fromRewrite;

  const host = String(req.headers?.['x-forwarded-host'] ?? req.headers?.host ?? 'localhost').split(',')[0].trim();
  const pathname = new URL(req.url ?? '/', `https://${host}`).pathname.replace(/\/+$/, '');
  if (pathname.startsWith('/api/')) {
    const tail = pathname.slice('/api/'.length);
    if (tail && tail !== 'router') return tail.split('/').filter(Boolean);
  }
  return [];
}
