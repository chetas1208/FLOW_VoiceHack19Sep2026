"""Bounded, sanitized event stream and optional opt-in screenshot evidence."""
import hashlib
import io
import os
import re
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageChops

SECRET_PATTERN = re.compile(r'(?i)(bearer\s+)[^\s,;"\']+|((?:token|password|secret|api[_-]?key|authorization|cookie)\s*[:=]\s*)[^\s,;"\']+')
EMAIL_PATTERN = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
QUERY_PATTERN = re.compile(r'(https?://[^\s?]+)\?[^\s]+')


def scrub(message):
    text = str(message)[:2048]
    for secret in (v for k, v in os.environ.items() if (k.startswith('QA_TARGET_TOKEN_') or k in ('QA_API_TOKEN', 'QA_OTLP_INGEST_TOKEN')) and len(v) > 3):
        text = text.replace(secret, '[REDACTED]')
    text = SECRET_PATTERN.sub(lambda m: (m.group(1) or m.group(2)) + '[REDACTED]', text)
    text = EMAIL_PATTERN.sub('[EMAIL]', text)
    return QUERY_PATTERN.sub(r'\1?[REDACTED]', text)[:512]


class EventStream:
    """Thread-safe, bounded, monotonic sequence of events. No request or response bodies."""
    def __init__(self, *, keep_messages=False, max_events=500):
        self._events = deque(maxlen=max_events)
        self._lock = threading.Lock()
        self.keep_messages = keep_messages
        self._seq = 0
        self._dropped = 0

    def add(self, source, level, message, *, step=None, **safe_metadata):
        cleaned = scrub(message)
        with self._lock:
            self._seq += 1
            event = {'seq': self._seq, 'at': datetime.now(timezone.utc).isoformat(),
                     'source': source, 'level': level,
                     'fingerprint': hashlib.sha256(cleaned.encode()).hexdigest()[:16]}
            if self.keep_messages:
                event['message'] = cleaned
            if step:
                event['step'] = step
            for name, value in safe_metadata.items():
                if name in ('status', 'method', 'path') and type(value) in (str, int):
                    event[name] = value
            if len(self._events) == self._events.maxlen:
                self._dropped += 1
            self._events.append(event)
            return event.copy()

    def snapshot(self):
        with self._lock:
            return list(self._events)

    def since(self, seq):
        with self._lock:
            return [x for x in self._events if x['seq'] > seq]

    def dropped(self):
        with self._lock:
            return self._dropped

    def last_seq(self):
        with self._lock:
            return self._seq


class FileTail:
    """Tail an authorized local log *while* the UI is running, bounded in memory."""
    def __init__(self, path, events, *, interval=0.025):
        self.path = Path(path)
        self.events = events
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None
        self._offset = self.path.stat().st_size
        self._pending = b''

    def _poll(self):
        while not self._stop.wait(self.interval):
            try:
                size = self.path.stat().st_size
                if size < self._offset:
                    self._offset = 0
                    self._pending = b''
                with self.path.open('rb') as source:
                    source.seek(self._offset)
                    data = source.read(65536)
                    self._offset = source.tell()
                if not data:
                    continue
                # Bound line length and pending buffer even under hostile log flood.
                lines = (self._pending + data)[-65536:].split(b'\n')
                self._pending = lines.pop()[-2048:]
                if len(lines) > 100:
                    self.events.add('observer', 'warning', 'server log burst truncated')
                for line in lines[-100:]:
                    content = line.decode('utf-8', 'replace')
                    level = 'error' if re.search(r'\b(error|exception|fatal|traceback)\b', content, re.I) else 'info'
                    self.events.add('server_log', level, content)
            except OSError:
                self.events.add('server_log', 'error', 'log source unavailable')
                break

    def start(self):
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        return self


def image_difference(actual_png, baseline_path):
    """Deterministic pixel diff, not an AI or perceptual equivalence judgment."""
    with Image.open(io.BytesIO(actual_png)) as actual, Image.open(baseline_path) as baseline:
        if actual.size != baseline.size:
            return {'ratio': 1.0, 'size_mismatch': True,
                    'actual_size': list(actual.size), 'baseline_size': list(baseline.size)}
        image_a, image_b = actual.convert('RGB'), baseline.convert('RGB')
        diff = ImageChops.difference(image_a, image_b).convert('L')
        histogram = diff.histogram()
        changed = sum(histogram[1:])
        return {'ratio': changed / (image_a.width * image_a.height), 'size_mismatch': False,
                'actual_size': list(image_a.size), 'baseline_size': list(image_b.size)}


def save_screenshot(root, run_id, step, data):
    """Private, content-addressed screenshot. Never served by public evidence API."""
    digest = hashlib.sha256(data).hexdigest()
    directory = Path(root).resolve() / 'private-screenshots' / run_id
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / (digest + '.png')
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'wb') as out:
                out.write(data)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    return {'sha256': digest, 'bytes': len(data), 'private_path': str(path)}
