"""Read-only browser discovery and a real browser regression against synthetic fixtures.

In restricted environments Chromium may block localhost networking. A scoped
Playwright route can relay only fixture-origin HTTP through Python, while the
browser still renders the page, runs JavaScript, and executes UI interactions.
This relay is NOT a substitute for an unrestricted real-network browser test.
"""
import json
import os
from urllib.parse import urlsplit, urljoin
import httpx
from reference_apps.fullstack.app import Handler, ORDERS
from http.server import ThreadingHTTPServer
from threading import Thread
from services.engine.manifest import approved_base_url


def fixture_route(page, origin):
    """Bridge ONLY the explicitly trusted fixture origin, without ambient proxies."""
    origin = approved_base_url(origin)
    def relay(route):
        request = route.request
        url = request.url
        parts = urlsplit(url)
        if f'{parts.scheme}://{parts.netloc}' != origin:
            route.abort('blockedbyclient')
            return
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=4) as client:
            try:
                response = client.request(request.method, url,
                    content=request.post_data_buffer,
                    headers={k: v for k, v in request.headers.items()
                             if k.lower() in ('content-type', 'accept')})
                if len(response.content) > 1_048_576:
                    route.abort('blockedbyclient')
                    return
                route.fulfill(status=response.status_code,
                    headers={k: v for k, v in response.headers.items()
                             if k.lower() in ('content-type',)}, body=response.body if hasattr(response, 'body') else response.content)
            except httpx.HTTPError:
                route.abort('failed')
    page.route('**/*', relay)


def fixture_content_bridge(page, origin):
    """Restricted-runtime fallback: actual Python HTTP + Chromium DOM/JS events.

    Does not verify native Chromium networking; must never be used for real sites.
    """
    origin = approved_base_url(origin)
    def python_fetch(source, path, options):
        url = urljoin(origin + '/', path)
        parts = urlsplit(url)
        if f'{parts.scheme}://{parts.netloc}' != origin:
            raise ValueError('browser bridge cross-origin request refused')
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=4) as client:
            response = client.request(options.get('method', 'GET'), url,
                content=options.get('body'),
                headers={k:v for k,v in options.get('headers',{}).items()
                         if k.lower() in ('content-type','accept')})
            if len(response.content) > 1_048_576:
                raise ValueError('fixture response exceeds 1MiB')
            return {'status':response.status_code,'body':response.text,
                    'content_type':response.headers.get('content-type','application/json')}
    page.expose_binding('__qa_fixture_http', python_fetch)
    with httpx.Client(trust_env=False, timeout=4) as client:
        html = client.get(origin + '/').text
    page.set_content(html, wait_until='load')
    page.evaluate('''() => {
      window.fetch = async (path, options={}) => {
        const r = await window.__qa_fixture_http(path, options);
        return new Response(r.body, {status:r.status, headers:{'Content-Type':r.content_type}});
      };
    }''')


def verify_browser_retry():
    from playwright.sync_api import sync_playwright
    ORDERS.clear()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as playwright:
            executable = os.getenv('QA_CHROMIUM_PATH') or ('/usr/bin/chromium' if os.path.exists('/usr/bin/chromium') else None)
            browser = playwright.chromium.launch(headless=True, executable_path=executable)
            try:
                page = browser.new_page()
                if os.getenv('QA_BROWSER_FIXTURE_RELAY') == '1':
                    fixture_content_bridge(page, origin)
                else:
                    page.goto(origin + '/', wait_until='domcontentloaded', timeout=10000)
                page.get_by_role('button', name='Create order').click()
                page.wait_for_function('document.querySelector("#result").textContent.includes("charge_count")')
                page.get_by_role('button', name='Create order').click()
                page.wait_for_function('JSON.parse(document.querySelector("#result").textContent).charge_count === 2')
                actual = len(ORDERS['browser-order']['charges'])
                return {'verdict': 'PASS' if actual == 1 else 'FAIL',
                        'server_charge_count': actual, 'title': page.title(),
                        'browser_executed': True,
                        'fixture_relay': os.getenv('QA_BROWSER_FIXTURE_RELAY') == '1'}
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        ORDERS.clear()


def discover_browser(origin, max_pages=8, fixture_relay=False):
    """Safe, read-only same-origin discovery; never submits forms or clicks writes."""
    from playwright.sync_api import sync_playwright
    origin = approved_base_url(origin)
    if not 1 <= max_pages <= 20:
        raise ValueError('max_pages must be 1..20')
    visited = set()
    queued = [origin + '/']
    pages = []
    with sync_playwright() as playwright:
        executable = os.getenv('QA_CHROMIUM_PATH') or ('/usr/bin/chromium' if os.path.exists('/usr/bin/chromium') else None)
        browser = playwright.chromium.launch(headless=True, executable_path=executable)
        try:
            page = browser.new_page()
            if fixture_relay:
                fixture_content_bridge(page, origin)
            while queued and len(pages) < max_pages:
                url = queued.pop(0)
                if url in visited:
                    continue
                if f'{urlsplit(url).scheme}://{urlsplit(url).netloc}' != origin:
                    continue
                visited.add(url)
                if fixture_relay:
                    with httpx.Client(trust_env=False, timeout=4) as client:
                        raw = client.get(url)
                    page.set_content(raw.text, wait_until='load')
                    response_status = raw.status_code
                else:
                    response = page.goto(url, wait_until='domcontentloaded', timeout=10000)
                    response_status = response.status if response else None
                data = page.evaluate('''() => ({
                  title: document.title,
                  headings: [...document.querySelectorAll('h1,h2')].map(x=>x.textContent.trim()).slice(0,30),
                  buttons: [...document.querySelectorAll('button')].map(x=>x.textContent.trim()).slice(0,40),
                  forms: [...document.forms].map(f=>({method:f.method,action:f.action})).slice(0,20),
                  links: [...document.querySelectorAll('a[href]')].map(a=>a.href).slice(0,100)
                })''')
                links = data.pop('links')
                for link in links:
                    resolved = urljoin(url, link).split('#', 1)[0]
                    if f'{urlsplit(resolved).scheme}://{urlsplit(resolved).netloc}' == origin and resolved not in visited and resolved not in queued:
                        queued.append(resolved)
                pages.append({'path': urlsplit(url).path, 'status': response_status, **data})
        finally:
            browser.close()
    return {'origin': origin, 'pages': pages, 'pages_discovered': len(pages),
            'read_only': True, 'fixture_relay': fixture_relay}
