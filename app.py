"""Local-only browser app. Run: python app.py"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from core import run

ROOT = Path(__file__).parent / 'static'
LOCK = threading.Lock()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Do not log briefs, generated text or credentials.

    def reply(self, status, body, content_type='application/json; charset=utf-8'):
        raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def trusted(self):
        allowed = {f'localhost:{self.server.server_port}', f'127.0.0.1:{self.server.server_port}'}
        return self.headers.get('Host') in allowed

    def do_GET(self):
        if not self.trusted():
            return self.reply(403, {'error': 'Local access only.'})
        path = urlparse(self.path).path
        if path == '/api/example':
            return self.reply(200, json.loads((ROOT.parent/'examples/synthetic-study.json').read_text()))
        files = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
        if path not in files:
            return self.reply(404, {'error': 'Not found.'})
        filename, mime = files[path]
        self.reply(200, (ROOT / filename).read_bytes(), mime)

    def do_POST(self):
        origin = self.headers.get('Origin')
        if not self.trusted() or origin != 'http://' + self.headers.get('Host', ''):
            return self.reply(403, {'error': 'Same-origin browser requests only.'})
        if self.path != '/api/generate':
            return self.reply(404, {'error': 'Not found.'})
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.reply(415, {'error': 'JSON required.'})
        if not LOCK.acquire(blocking=False):
            return self.reply(429, {'error': 'A request is already running.'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 250000:
                raise ValueError('Request is too large or empty.')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict) or data.get('mode') not in ['demo', 'live']:
                raise ValueError('Choose demo or live mode.')
            result = run(data)
            self.reply(200, result)
        except (ValueError, UnicodeError) as error:
            self.reply(400, {'error': str(error)})
        except RuntimeError as error:
            self.reply(502, {'error': str(error)})
        except Exception:
            self.reply(500, {'error': 'Unexpected response. Check your configuration and try again.'})
        finally:
            LOCK.release()

if __name__ == '__main__':
    print('Persona Research Lab: http://127.0.0.1:8081 — Ctrl+C to stop')
    ThreadingHTTPServer(('127.0.0.1', 8081), Handler).serve_forever()
