#!/usr/bin/env python3
"""FPL Brain local server: static UI + cautious read-only FPL proxy + optional AI.
No external packages required. Python 3.10+ recommended.
"""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import urlparse
from pathlib import Path
import json, os, time, threading

ROOT = Path(__file__).resolve().parent
HOST = os.getenv('FPL_BRAIN_HOST', '127.0.0.1')
PORT = int(os.getenv('FPL_BRAIN_PORT', '8000'))
FPL_BASE = 'https://fantasy.premierleague.com/api'
_cache = {}
_cache_lock = threading.Lock()
CACHE_SECONDS = int(os.getenv('FPL_CACHE_SECONDS', '600'))
MAX_BODY = 64 * 1024


def json_bytes(obj):
    return json.dumps(obj, ensure_ascii=False).encode('utf-8')


def fetch_fpl(path):
    now = time.time()
    with _cache_lock:
        item = _cache.get(path)
        if item and now - item['at'] < CACHE_SECONDS:
            return item['data'], True, item['at']
    url = FPL_BASE + path
    req = Request(url, headers={
        'User-Agent': 'FPL-Brain-independent-prototype/0.2 (read-only; respectful caching)',
        'Accept': 'application/json',
    })
    with urlopen(req, timeout=12) as response:
        if response.status != 200:
            raise RuntimeError(f'Upstream returned HTTP {response.status}')
        data = json.loads(response.read().decode('utf-8'))
    # Guard against an unexpected response shape.
    if not isinstance(data, (dict, list)):
        raise RuntimeError('Unexpected upstream response format')
    with _cache_lock:
        _cache[path] = {'data': data, 'at': now}
    return data, False, now


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        print('[FPL Brain] ' + (fmt % args))

    def send_json(self, status, obj):
        body = json_bytes(obj)
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        try:
            n = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            n = 0
        if n < 1 or n > MAX_BODY:
            raise ValueError('Request body must be between 1 byte and 64 KB')
        raw = self.rfile.read(n)
        return json.loads(raw.decode('utf-8'))

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/health':
            self.send_json(200, {
                'ok': True,
                'app': 'FPL Brain',
                'version': '0.2',
                'server_time_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'ai_configured': bool(os.getenv('FPL_AI_API_KEY') and os.getenv('FPL_AI_MODEL')),
                'fpl_source': 'public FPL endpoint; undocumented and may change',
            })
            return
        if path in ('/api/fpl/bootstrap', '/api/fpl/fixtures'):
            upstream_path = '/bootstrap-static/' if path.endswith('bootstrap') else '/fixtures/'
            try:
                data, cached, fetched_at = fetch_fpl(upstream_path)
                self.send_json(200, {
                    'ok': True, 'data': data, 'cached': cached,
                    'fetched_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(fetched_at)),
                    'source': 'https://fantasy.premierleague.com/api' + upstream_path,
                    'notice': 'Public endpoint is undocumented, can change, and availability is not guaranteed.'
                })
            except (URLError, HTTPError, TimeoutError, RuntimeError, json.JSONDecodeError) as e:
                self.send_json(502, {
                    'ok': False, 'error': 'Live FPL data could not be retrieved.',
                    'detail': str(e), 'source': 'https://fantasy.premierleague.com/',
                    'cached_data_available': False,
                    'notice': 'No live data was supplied. Check internet access and try again later.'
                })
            return
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path != '/api/ai/chat':
            self.send_json(404, {'ok': False, 'error': 'Unknown API route'})
            return
        api_key = os.getenv('FPL_AI_API_KEY', '').strip()
        model = os.getenv('FPL_AI_MODEL', '').strip()
        base_url = os.getenv('FPL_AI_BASE_URL', 'https://api.openai.com/v1').strip().rstrip('/')
        if not api_key or not model:
            self.send_json(503, {
                'ok': False, 'error': 'AI provider is not configured.',
                'detail': 'Set FPL_AI_API_KEY and FPL_AI_MODEL in your server environment. No key is stored in the browser.'
            })
            return
        try:
            body = self.read_body()
            messages = body.get('messages', [])
            if not isinstance(messages, list) or not messages or len(messages) > 20:
                raise ValueError('Provide 1–20 chat messages')
            safe_messages = []
            for msg in messages:
                if not isinstance(msg, dict) or msg.get('role') not in ('system', 'user', 'assistant'):
                    continue
                content = msg.get('content', '')
                if not isinstance(content, str):
                    continue
                safe_messages.append({'role': msg['role'], 'content': content[:8000]})
            payload = json_bytes({'model': model, 'messages': safe_messages, 'temperature': 0.2})
            req = Request(base_url + '/chat/completions', data=payload, method='POST', headers={
                'Authorization': 'Bearer ' + api_key,
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            })
            with urlopen(req, timeout=35) as response:
                result = json.loads(response.read().decode('utf-8'))
            text = result.get('choices', [{}])[0].get('message', {}).get('content', '')
            if not isinstance(text, str) or not text:
                raise RuntimeError('AI provider returned no message text')
            self.send_json(200, {'ok': True, 'answer': text, 'model': model})
        except ValueError as e:
            self.send_json(400, {'ok': False, 'error': str(e)})
        except (URLError, HTTPError, TimeoutError, RuntimeError, json.JSONDecodeError, IndexError, KeyError) as e:
            self.send_json(502, {'ok': False, 'error': 'AI provider request failed.', 'detail': str(e)})


def main():
    print(f'FPL Brain v0.2: http://{HOST}:{PORT}')
    print('Live data and AI are optional; the server reports failures instead of inventing data.')
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

if __name__ == '__main__':
    main()
