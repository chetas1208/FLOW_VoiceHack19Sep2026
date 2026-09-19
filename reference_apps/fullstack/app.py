"""Intentionally defective local HTTP reference app. Never deploy publicly."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

ORDERS = {}

def create_order(order_id, amount):
    # KNOWN DEFECT FS-001: retry creates a duplicate charge rather than idempotent result.
    entry = ORDERS.setdefault(order_id, {"charges": [], "amount": amount})
    entry["charges"].append(amount)
    return {"order_id": order_id, "charge_count": len(entry["charges"])}

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != '/orders':
            self.send_error(404); return
        size = int(self.headers.get('Content-Length', '0'))
        try:
            payload = json.loads(self.rfile.read(size))
            result = create_order(payload['order_id'], payload['amount'])
        except (ValueError, KeyError, TypeError):
            self.send_error(400); return
        body = json.dumps(result).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)

if __name__ == '__main__':
    HTTPServer(('127.0.0.1', 8765), Handler).serve_forever()

# A minimal UI for the optional real-browser integration smoke test.
# Installed at module load so existing POST behavior is preserved.
def _reference_get(self):
    if self.path != '/':
        self.send_error(404)
        return
    body = (b'<!doctype html><html><head><title>QA reference orders</title></head>'
            b'<body><h1>Order reference</h1><label for="order">Order ID</label>'
            b'<input id="order" value="browser-order"><button id="submit">Create order</button>'
            b'<output id="result" aria-live="polite"></output>'
            b'<script>document.querySelector("#submit").onclick=async()=>{'
            b'const r=await fetch("/orders",{method:"POST",headers:{"Content-Type":"application/json"},'
            b'body:JSON.stringify({order_id:document.querySelector("#order").value,amount:50})});'
            b'document.querySelector("#result").textContent=JSON.stringify(await r.json());};</script>'
            b'</body></html>')
    self.send_response(200)
    self.send_header('Content-Type','text/html; charset=utf-8')
    self.send_header('Content-Length',str(len(body)))
    self.end_headers()
    self.wfile.write(body)
Handler.do_GET = _reference_get
