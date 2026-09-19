/**
 * Server-sent event hub with replay.
 *
 * Every broadcast gets a global sequence number and is kept in a bounded ring
 * buffer. A client that reconnects sends `Last-Event-ID` (or `?since=`) and
 * receives exactly what it missed, so a dropped connection does not leave the
 * dashboard silently stale.
 */
const BUFFER_SIZE = 500;

export function createEventHub() {
  const clients = new Set();
  const buffer = [];
  let seq = 0;

  function record(payload) {
    seq += 1;
    const entry = { seq, ...payload };
    buffer.push(entry);
    if (buffer.length > BUFFER_SIZE) buffer.shift();
    return entry;
  }

  function write(res, entry) {
    try {
      res.write(`id: ${entry.seq}\nevent: ${entry.type}\ndata: ${JSON.stringify(entry)}\n\n`);
      return true;
    } catch {
      clients.delete(res);
      return false;
    }
  }

  return {
    get clientCount() {
      return clients.size;
    },
    get seq() {
      return seq;
    },

    broadcast(payload) {
      const entry = record(payload);
      for (const res of clients) write(res, entry);
      return entry;
    },

    /** Attach a client, replaying anything after `since`. */
    subscribe(req, res, since) {
      res.writeHead(200, {
        'Content-Type': 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache, no-transform',
        Connection: 'keep-alive',
        'X-Accel-Buffering': 'no',
      });
      res.write(`retry: 2000\n\n`);

      const from = Number(req.headers['last-event-id'] ?? since ?? 0) || 0;
      const missed = buffer.filter((e) => e.seq > from);
      if (from && missed.length) {
        res.write(`event: stream.resumed\ndata: ${JSON.stringify({ from, replaying: missed.length, seq })}\n\n`);
      } else {
        // Tell the client whether a gap is unrecoverable so it can re-snapshot.
        const gap = from > 0 && buffer.length && buffer[0].seq > from + 1;
        res.write(`event: stream.connected\ndata: ${JSON.stringify({ seq, gap, resnapshot: gap || from === 0 })}\n\n`);
      }
      for (const entry of missed) write(res, entry);

      clients.add(res);
      req.on('close', () => clients.delete(res));
      return res;
    },

    heartbeat() {
      for (const res of clients) {
        try {
          res.write(`: ping ${Date.now()}\n\n`);
        } catch {
          clients.delete(res);
        }
      }
    },

    closeAll() {
      for (const res of clients) {
        try {
          res.end();
        } catch { /* already gone */ }
      }
      clients.clear();
    },
  };
}
