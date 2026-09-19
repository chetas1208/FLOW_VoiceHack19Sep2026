"""Cold-start UI inventory: bounded, read-only, same-origin routes and controls.

Proposes scenarios without auto-clicking, form submissions, or mutation approval.
"""
import hashlib
from collections import deque
from urllib.parse import urlsplit

from services.universal_ui.drivers import UnsupportedAction, open_driver
from services.universal_ui.evidence import EventStream
from services.universal_ui.spec import validate

AVOID_GET = ('delete', 'remove', 'logout', 'signout', 'purchase', 'pay', 'transfer', 'unsubscribe', 'terminate')


def discover(spec, *, max_pages=10, graph=None):
    if not 1 <= max_pages <= 30:
        raise ValueError('max_pages must be 1..30')
    # Explicitly separate discovery from the owner-authored execution contract.
    if spec.get('driver', 'web') != 'web':
        raise UnsupportedAction('read-only DOM crawler currently requires a web UI')
    if spec.get('allow_mutations') or spec.get('allow_destructive'):
        raise ValueError('discovery must run without mutation permissions')
    opts = {k: v for k, v in spec.items() if k in (
        'id', 'origin', 'driver', 'browser', 'viewport', 'fixture_relay', 'timeout_ms', 'auth_env')}
    opts['steps'] = [{'name': 'landing', 'action': 'goto', 'path': '/'}]
    validate(opts)
    origin = opts['origin'].rstrip('/')
    queue = deque(['/'])
    seen = set()
    pages = []
    drafts = []
    skipped = []
    events = EventStream()
    driver = open_driver(opts, events)
    try:
        while queue and len(pages) < max_pages:
            path = queue.popleft()
            if path in seen:
                continue
            if any(token in path.lower() for token in AVOID_GET):
                skipped.append(path)
                continue
            seen.add(path)
            try:
                status = driver.navigate(path)
                if hasattr(driver, 'settle'):
                    driver.settle()
                page = driver.discover()
            except Exception:
                pages.append({'path': path, 'status': 'UNAVAILABLE', 'controls': [], 'links': 0})
                continue
            links = page.pop('links')
            approved = []
            for url in links:
                parsed = urlsplit(url)
                root = urlsplit(origin)
                if (parsed.scheme, parsed.hostname, parsed.port) != (root.scheme, root.hostname, root.port):
                    continue
                candidate = parsed.path or '/'
                if any(token in candidate.lower() for token in AVOID_GET):
                    if candidate not in skipped:
                        skipped.append(candidate)
                    continue
                if candidate not in seen and candidate not in queue:
                    queue.append(candidate)
                if candidate != path and candidate not in approved:
                    approved.append(candidate)
            controls = page['controls']
            for index, control in enumerate(controls):
                if control.get('tag') not in ('button', 'input', 'select', 'textarea'):
                    continue
                locator = ({'by': 'test_id', 'value': control['test_id']}
                           if control.get('test_id') else
                           {'by': 'id', 'value': control['id']}
                           if control.get('id') else
                           {'by': 'role', 'value': 'button'}
                           if control['tag'] == 'button' else None)
                if locator is None:
                    continue
                scenario_id = 'suggest-' + hashlib.sha256((path + '|' + str(locator)).encode()).hexdigest()[:12]
                drafts.append({'id': scenario_id, 'path': path, 'locator': locator,
                               'proposal': 'Owner should define expected outcome and independent state oracle',
                               'status': 'PROPOSED_REQUIRES_OWNER_APPROVAL',
                               'mutation_permission_granted': False})
            pages.append({'path': path, 'http_status': status, 'title': page['title'][:200],
                          'title_fingerprint': hashlib.sha256(page['title'].encode()).hexdigest()[:16],
                          'headings': page['headings'], 'heading_count': len(page['headings']),
                          'landmarks': page.get('landmarks', []), 'forms': page.get('forms', []),
                          'live_regions': page.get('live_regions', []), 'controls': controls,
                          'aria_snapshot': page.get('aria_snapshot'),
                          'discovered_links': approved[:30]})
            if graph is not None:
                project = spec.get('project_id', 'local'); version = spec.get('version', 'unversioned')
                name = f'{project}:ui:{path}'
                graph.node(name, 'ui_page', version, {'path': path, 'control_count': len(controls)}, 'browser-discovery:' + spec['id'])
                for next_path in approved:
                    dest = f'{project}:ui:{next_path}'
                    graph.node(dest, 'ui_page', version, {'path': next_path}, 'browser-discovery:' + spec['id'])
                    graph.edge(name, dest, 'NAVIGATES_TO', version, 'browser-discovery:' + spec['id'])
    finally:
        driver.close()
    return {'origin': origin, 'driver': 'web', 'read_only': True, 'pages': pages,
            'page_count': len(pages), 'truncated': bool(queue), 'drafts': drafts[:100],
            'skipped_unsafe_links': skipped[:50],
            'proposed_scenarios_approved': False, 'network_mode': 'fixture_relay'
            if spec.get('fixture_relay') else 'native_browser'}
