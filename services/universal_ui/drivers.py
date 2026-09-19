"""UI drivers share bounded interactions, not a claim of universal feature support.

Playwright drives web; W3C WebDriver sessions can drive web/native surfaces when
an owner supplies a running compatible browser/Appium server. No shell execution.
"""
import base64
import json
import os
import time
from urllib.parse import urlsplit

import httpx

from services.engine.manifest import approved_base_url
from services.universal_ui.evidence import scrub


class UnsupportedAction(RuntimeError):
    """This backend does not provide the requested UI capability."""


class DriverError(RuntimeError):
    """Transport failure or driver protocol error, deliberately without raw bodies."""


def _same_origin(url, origin):
    target = urlsplit(url)
    root = urlsplit(origin)
    return (target.scheme, target.hostname, target.port) == (root.scheme, root.hostname, root.port)


class PlaywrightDriver:
    kind = 'web'
    def __init__(self, spec, events):
        from playwright.sync_api import sync_playwright
        self.spec = spec
        self.events = events
        self.origin = approved_base_url(spec['origin'])
        self.fixture_relay = spec.get('fixture_relay', False)
        self._playwright = sync_playwright().start()
        self.browser = None
        self.context = None
        try:
            browser_name = spec.get('browser', 'chromium')
            options = {'headless': True}
            if browser_name == 'chromium':
                custom = os.getenv('QA_CHROMIUM_PATH') or ('/usr/bin/chromium' if os.path.isfile('/usr/bin/chromium') else None)
                if custom:
                    options['executable_path'] = custom
            self.browser = getattr(self._playwright, browser_name).launch(**options)
            self.context = self.browser.new_context(viewport=spec.get('viewport', {'width': 1280, 'height': 800}),
                                                    accept_downloads=False, service_workers='block',
                                                    ignore_https_errors=False)
            self.page = self.context.new_page()
            self.page.set_default_timeout(spec.get('timeout_ms', 5000))
            self.page.on('console', self._console)
            self.page.on('pageerror', lambda error: events.add('page_error', 'error', str(error)))
            self.page.on('requestfailed', lambda request: events.add('network', 'error',
                               'request failed: ' + request.method, method=request.method,
                               path=urlsplit(request.url).path[:128]))
            self.page.on('response', self._response)
            self.page.on('dialog', lambda dialog: dialog.dismiss())
            self.page.on('download', lambda download: download.cancel())
            if self.fixture_relay:
                self._install_fixture_bridge()
            else:
                self.page.route('**/*', self._guard_route)
        except BaseException:
            self.close()
            raise

    def _console(self, msg):
        self.events.add('console', 'error' if msg.type == 'error' else msg.type, str(msg.text))

    def _response(self, response):
        status = response.status
        self.events.add('network', 'error' if status >= 400 else 'info',
                        'HTTP response', status=status, method=response.request.method,
                        path=urlsplit(response.url).path[:128])

    def _guard_route(self, route):
        url = route.request.url
        if not _same_origin(url, self.origin):
            self.events.add('network', 'error', 'cross-origin request blocked')
            route.abort('blockedbyclient')
            return
        if self.spec.get('propagate_trace') and getattr(self, 'traceparent', None):
            headers = dict(route.request.headers)
            headers['traceparent'] = self.traceparent
            route.continue_(headers=headers)
        else:
            route.continue_()

    def _install_fixture_bridge(self):
        # Fixture-only bypass for environments where Chromium localhost network
        # is unavailable. Executes actual DOM/JS, but Python relays HTTP.
        if not self.origin.startswith(('http://127.0.0.1:', 'http://localhost:')):
            raise DriverError('fixture relay requires a loopback fixture')
        origin = self.origin
        events = self.events
        def bridge(source, path, options):
            from urllib.parse import urljoin
            url = urljoin(origin + '/', path)
            if not _same_origin(url, origin):
                raise DriverError('fixture bridge denied cross-origin request')
            method = options.get('method', 'GET').upper()
            if method not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
                raise DriverError('fixture bridge denied method')
            if method != 'GET' and not self.spec.get('allow_mutations'):
                raise DriverError('fixture bridge requires mutation approval')
            headers = {k: v for k, v in options.get('headers', {}).items()
                       if k.lower() in ('accept', 'content-type') and isinstance(v, str)}
            if self.spec.get('propagate_trace') and getattr(self, 'traceparent', None):
                headers['traceparent'] = self.traceparent
            try:
                with httpx.Client(trust_env=False, follow_redirects=False, timeout=5) as client:
                    with client.stream(method, url, content=options.get('body'), headers=headers) as response:
                        data = b''
                        for chunk in response.iter_bytes():
                            data += chunk
                            if len(data) > 1_048_576:
                                raise DriverError('fixture bridge response too large')
                        events.add('network', 'error' if response.status_code >= 400 else 'info',
                                   'fixture HTTP relay', status=response.status_code, method=method,
                                   path=urlsplit(url).path[:128])
                        return {'status': response.status_code, 'body': data.decode('utf-8', 'replace'),
                                'content_type': response.headers.get('content-type', 'text/plain')}
            except httpx.HTTPError as exc:
                events.add('network', 'error', 'fixture HTTP relay failed')
                raise DriverError('fixture network unavailable') from exc
        self.page.expose_binding('__qa_http', bridge)

    def _fixture_navigate(self, path):
        from urllib.parse import urljoin
        url = urljoin(self.origin + '/', path.lstrip('/'))
        if not _same_origin(url, self.origin):
            raise DriverError('cross-origin navigation denied')
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=5) as client:
            response = client.get(url)
        if response.is_redirect or len(response.content) > 1_048_576:
            raise DriverError('fixture navigation redirect or oversize response denied')
        self.events.add('network', 'error' if response.status_code >= 400 else 'info',
                        'fixture navigation', status=response.status_code,
                        method='GET', path=urlsplit(url).path[:128])
        self.page.set_content(response.text, wait_until='load')
        self.page.evaluate('''() => { window.fetch = async (url, options={}) => {
            const r = await window.__qa_http(url, options);
            return new Response(r.body, {status:r.status,headers:{'Content-Type':r.content_type}});
        }; }''')
        self._fixture_path = path

    def navigate(self, path):
        if self.fixture_relay:
            return self._fixture_navigate(path)
        response = self.page.goto(self.origin + path, wait_until='domcontentloaded',
                                  timeout=self.spec.get('timeout_ms', 5000))
        if not _same_origin(self.page.url, self.origin):
            raise DriverError('navigation redirected outside approved origin')
        return response.status if response else None

    def locator(self, locator):
        by = locator['by']
        value = locator['value']
        exact = locator.get('exact', True)
        selectors = {
            'role': lambda: self.page.get_by_role(value, exact=exact),
            'text': lambda: self.page.get_by_text(value, exact=exact),
            'test_id': lambda: self.page.get_by_test_id(value),
            'label': lambda: self.page.get_by_label(value, exact=exact),
            'placeholder': lambda: self.page.get_by_placeholder(value, exact=exact),
            'css': lambda: self.page.locator(value),
            'id': lambda: self.page.locator('[id=' + json.dumps(value) + ']'),
            'xpath': lambda: self.page.locator('xpath=' + value),
            'class_name': lambda: self.page.locator('[class~=' + json.dumps(value) + ']'),
            'accessibility_id': lambda: self.page.get_by_label(value, exact=exact),
        }
        return selectors[by]()

    def action(self, step):
        action = step['action']
        if action == 'goto':
            return self.navigate(step['path'])
        if action == 'screenshot':
            return self.screenshot()
        if action in ('assert_url', 'assert_title'):
            return self.current_url() if action == 'assert_url' else self.title()
        item = self.locator(step['locator'])
        if action == 'click': item.click()
        elif action == 'fill': item.fill(str(step['value']))
        elif action == 'press': item.press(str(step['value']))
        elif action == 'check': item.check()
        elif action == 'uncheck': item.uncheck()
        elif action == 'select': item.select_option(str(step['value']))
        elif action == 'hover': item.hover()
        elif action == 'wait_for': item.wait_for(state='visible', timeout=step.get('timeout_ms', self.spec.get('timeout_ms', 5000)))
        elif action == 'assert_text': return item.inner_text(timeout=step.get('timeout_ms', self.spec.get('timeout_ms', 5000)))
        elif action == 'assert_visible': return item.is_visible()
        elif action == 'assert_count': return item.count()
        elif action == 'assert_value': return item.input_value()
        else: raise UnsupportedAction('unsupported Playwright action')

    def title(self): return self.page.title()
    def current_url(self):
        return self.origin + getattr(self, '_fixture_path', '/') if self.fixture_relay else self.page.url
    def screenshot(self): return self.page.screenshot(full_page=False, animations='disabled', timeout=5000)

    def discover(self):
        return self.page.evaluate('''() => ({ title: document.title,
          headings: [...document.querySelectorAll('h1,h2')].slice(0,20).map(x=>x.textContent.trim().slice(0,120)),
          links: [...document.querySelectorAll('a[href]')].slice(0,100).map(a=>a.href),
          controls: [...document.querySelectorAll('button,input,select,textarea,[role="button"]')].slice(0,60).map(x=>({
            tag:x.tagName.toLowerCase(), role:x.getAttribute('role'), type:x.getAttribute('type'),
            test_id:x.getAttribute('data-testid'), label:x.getAttribute('aria-label'),
            id:x.id, text:(x.innerText||'').trim().slice(0,100)}))
        })''')

    def close(self):
        try:
            if self.context: self.context.close()
            if self.browser: self.browser.close()
        finally:
            self._playwright.stop()


class WebDriver:
    """Subset of W3C WebDriver plus Appium accessibility-id extension.

    Native/mobile support requires a preconfigured, owner-operated Appium server.
    Unsupported capability is explicit, never silently counted as a pass.
    """
    kind = 'webdriver'
    ELEMENT_KEY = 'element-6066-11e4-a52e-4f735466cecf'

    def __init__(self, spec, events):
        self.spec = spec
        self.events = events
        self.endpoint = approved_base_url(spec['webdriver_url'])
        self.client = httpx.Client(trust_env=False, follow_redirects=False, timeout=10)
        self.session = None
        try:
            response = self._request('POST', '/session', {'capabilities': {'alwaysMatch': spec.get('capabilities', {})}})
            value = response.get('value') or {}
            session = value.get('sessionId') if isinstance(value, dict) else None
            self.session = session or response.get('sessionId')
            if not isinstance(self.session, str) or not self.session:
                raise DriverError('WebDriver failed to create a session')
        except BaseException:
            self.client.close()
            raise

    def _request(self, method, path, payload=None):
        try:
            r = self.client.request(method, self.endpoint + path, json=payload,
                                    headers={'accept': 'application/json'})
            if len(r.content) > 1_048_576:
                raise DriverError('WebDriver response too large')
            body = r.json() if r.content else {}
            value = body.get('value', {})
            if r.status_code >= 400 or (isinstance(value, dict) and value.get('error')):
                kind = value.get('error', 'protocol failure') if isinstance(value, dict) else 'protocol failure'
                raise DriverError('WebDriver: ' + scrub(kind))
            return body
        except (httpx.HTTPError, ValueError) as exc:
            raise DriverError('WebDriver transport or JSON error') from exc

    def _session(self, path): return '/session/' + self.session + path

    def navigate(self, path):
        if 'origin' not in self.spec:
            raise UnsupportedAction('native WebDriver session has no HTTP origin for goto')
        self._request('POST', self._session('/url'), {'url': approved_base_url(self.spec['origin']) + path})
        url = self.current_url()
        if not _same_origin(url, self.spec['origin']):
            raise DriverError('WebDriver navigated outside approved origin')

    def _strategy(self, locator):
        by = locator['by']; value = locator['value']
        if by == 'accessibility_id': return 'accessibility id', value  # Appium extension
        if by == 'xpath': return 'xpath', value
        if by == 'css': return 'css selector', value
        if by == 'id': return 'css selector', '[id=' + json.dumps(value) + ']'
        if by == 'test_id': return 'css selector', '[data-testid=' + json.dumps(value) + ']'
        if by == 'class_name': return 'class name', value
        if by == 'text':
            if '\"' in value and "'" in value:
                raise UnsupportedAction('use an explicit XPath for mixed-quote text')
            literal = "'" + value + "'" if '\"' in value else '"' + value + '"'
            return 'xpath', '//*[normalize-space(text())=' + literal + ']'
        raise UnsupportedAction('WebDriver locator strategy unavailable: ' + by)

    def _element(self, locator):
        strategy, selector = self._strategy(locator)
        body = self._request('POST', self._session('/element'), {'using': strategy, 'value': selector})
        obj = body.get('value')
        if not isinstance(obj, dict) or self.ELEMENT_KEY not in obj:
            raise DriverError('WebDriver did not return a W3C element')
        return self._session('/element/' + obj[self.ELEMENT_KEY])

    def action(self, step):
        action = step['action']
        if action == 'goto': return self.navigate(step['path'])
        if action == 'screenshot': return self.screenshot()
        if action == 'assert_title': return self.title()
        if action == 'assert_url': return self.current_url()
        if action in ('hover', 'select', 'check', 'uncheck', 'press'):
            raise UnsupportedAction('WebDriver extension not implemented: ' + action)
        if action == 'assert_count':
            strategy, selector = self._strategy(step['locator'])
            found = self._request('POST', self._session('/elements'),
                                  {'using': strategy, 'value': selector}).get('value', [])
            if not isinstance(found, list):
                raise DriverError('WebDriver returned invalid element collection')
            return len(found)
        if action == 'wait_for':
            deadline = time.monotonic() + step.get('timeout_ms', self.spec.get('timeout_ms', 5000)) / 1000
            while True:
                try:
                    element = self._element(step['locator'])
                    if self._request('GET', element + '/displayed').get('value') is True:
                        return True
                except DriverError as exc:
                    if 'no such element' not in str(exc):
                        raise
                if time.monotonic() >= deadline:
                    raise TimeoutError('WebDriver element not visible before deadline')
                time.sleep(0.1)
        element = self._element(step['locator'])
        if action == 'click': self._request('POST', element + '/click', {})
        elif action == 'fill':
            self._request('POST', element + '/clear', {})
            text = str(step['value'])
            self._request('POST', element + '/value', {'text': text, 'value': list(text)})
        elif action == 'assert_text': return self._request('GET', element + '/text')['value']
        elif action == 'assert_visible': return self._request('GET', element + '/displayed')['value']
        elif action == 'assert_value': return self._request('GET', element + '/attribute/value')['value']
        else: raise UnsupportedAction('unknown WebDriver action')

    def current_url(self): return self._request('GET', self._session('/url'))['value']
    def title(self): return self._request('GET', self._session('/title'))['value']
    def screenshot(self):
        encoded = self._request('GET', self._session('/screenshot'))['value']
        if len(encoded) > 8_000_000:
            raise DriverError('WebDriver screenshot too large')
        return base64.b64decode(encoded, validate=True)
    def discover(self): raise UnsupportedAction('WebDriver accessibility-tree discovery not implemented')
    def close(self):
        try:
            if self.session:
                self._request('DELETE', self._session(''))
        finally:
            self.client.close()


def open_driver(spec, events):
    return WebDriver(spec, events) if spec.get('driver') == 'webdriver' else PlaywrightDriver(spec, events)
