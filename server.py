#!/usr/bin/env python3
"""FPL Brain v0.5: cached read-only FPL proxy, persistent snapshots and optional advanced stats."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import json, os, time, threading, sqlite3, hashlib

ROOT = Path(__file__).resolve().parent
HOST = os.getenv('FPL_BRAIN_HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', os.getenv('FPL_BRAIN_PORT', '8000')))
FPL_BASE = 'https://fantasy.premierleague.com/api'
DB_PATH = Path(os.getenv('FPL_DB_PATH', str(ROOT / 'fpl_brain.sqlite3')))
ADVANCED_STATS_URL = os.getenv('FPL_ADVANCED_STATS_URL', '').strip()
ADVANCED_STATS_TOKEN = os.getenv('FPL_ADVANCED_STATS_TOKEN', '').strip()
_cache, _cache_lock = {}, threading.Lock()
_advanced_cache = {'data': None, 'at': 0.0}
CACHE_SECONDS = max(60, int(os.getenv('FPL_CACHE_SECONDS', '600')))
MAX_BODY = 64 * 1024
DB_SCHEMA = '''
CREATE TABLE IF NOT EXISTS snapshots (
 id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, fetched_at REAL NOT NULL,
 source TEXT NOT NULL, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_kind_time ON snapshots(kind, fetched_at DESC);
CREATE TABLE IF NOT EXISTS feed_status (kind TEXT PRIMARY KEY, last_success_at REAL NOT NULL, latest_snapshot_id INTEGER);
CREATE TABLE IF NOT EXISTS player_snapshots (
 snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
 player_id INTEGER NOT NULL, web_name TEXT, team_id INTEGER, now_cost INTEGER,
 total_points INTEGER, minutes INTEGER, form REAL, expected_goals REAL,
 expected_assists REAL, expected_goal_involvements REAL, expected_goals_conceded REAL,
 ict_index REAL, selected_by_percent REAL, status TEXT,
 PRIMARY KEY(snapshot_id, player_id)
);
CREATE INDEX IF NOT EXISTS idx_player_history ON player_snapshots(player_id, snapshot_id);
'''


def json_bytes(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def utc_stamp(ts):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(ts))


def db_connect():
    con = sqlite3.connect(str(DB_PATH), timeout=8)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    return con


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db_connect() as con:
        con.executescript(DB_SCHEMA)


def persist_snapshot(kind, data, fetched_at, source):
    raw = json_bytes(data).decode('utf-8')
    digest = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    rows = []
    with db_connect() as con:
        previous = con.execute('SELECT id,payload_hash FROM snapshots WHERE kind=? ORDER BY fetched_at DESC LIMIT 1', (kind,)).fetchone()
        if previous and previous['payload_hash'] == digest:
            con.execute('INSERT INTO feed_status(kind,last_success_at,latest_snapshot_id) VALUES(?,?,?) ON CONFLICT(kind) DO UPDATE SET last_success_at=excluded.last_success_at, latest_snapshot_id=excluded.latest_snapshot_id', (kind, fetched_at, previous['id']))
            return {'stored': False, 'snapshot_id': previous['id'], 'reason': 'unchanged'}
        cur = con.execute('INSERT INTO snapshots(kind,fetched_at,source,payload_json,payload_hash) VALUES(?,?,?,?,?)', (kind, fetched_at, source, raw, digest))
        sid = cur.lastrowid
        if kind == 'bootstrap' and isinstance(data, dict):
            for p in data.get('elements', []):
                if not isinstance(p, dict) or not isinstance(p.get('id'), int):
                    continue
                def number(key):
                    v = p.get(key)
                    try: return float(v) if v is not None and v != '' else None
                    except (TypeError, ValueError): return None
                rows.append((sid, p['id'], p.get('web_name'), p.get('team'), p.get('now_cost'), p.get('total_points'), p.get('minutes'), number('form'), number('expected_goals'), number('expected_assists'), number('expected_goal_involvements'), number('expected_goals_conceded'), number('ict_index'), number('selected_by_percent'), p.get('status')))
            con.executemany('INSERT OR REPLACE INTO player_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
        # Keep the latest 180 changed snapshots per feed.
        con.execute('DELETE FROM snapshots WHERE kind=? AND id NOT IN (SELECT id FROM snapshots WHERE kind=? ORDER BY fetched_at DESC LIMIT 180)', (kind, kind))
        con.execute('INSERT INTO feed_status(kind,last_success_at,latest_snapshot_id) VALUES(?,?,?) ON CONFLICT(kind) DO UPDATE SET last_success_at=excluded.last_success_at, latest_snapshot_id=excluded.latest_snapshot_id', (kind, fetched_at, sid))
        return {'stored': True, 'snapshot_id': sid, 'players_saved': len(rows)}


def latest_snapshot(kind):
    try:
        with db_connect() as con:
            row = con.execute('SELECT fetched_at,source,payload_json FROM snapshots WHERE kind=? ORDER BY fetched_at DESC LIMIT 1', (kind,)).fetchone()
        return {'data': json.loads(row['payload_json']), 'fetched_at': row['fetched_at'], 'source': row['source']} if row else None
    except (sqlite3.Error, json.JSONDecodeError, OSError):
        return None


def fetch_fpl(path):
    now = time.time()
    with _cache_lock:
        item = _cache.get(path)
        if item and now - item['at'] < CACHE_SECONDS:
            return item['data'], True, item['at']
    url = FPL_BASE + path
    req = Request(url, headers={'User-Agent': 'FPL-Brain-independent-prototype/0.3 (read-only; respectful caching)', 'Accept': 'application/json'})
    with urlopen(req, timeout=12) as response:
        if response.status != 200:
            raise RuntimeError(f'Upstream returned HTTP {response.status}')
        data = json.loads(response.read().decode('utf-8'))
    if path == '/bootstrap-static/' and not (isinstance(data, dict) and isinstance(data.get('elements'), list) and isinstance(data.get('teams'), list)):
        raise RuntimeError('Bootstrap response is missing expected elements/teams arrays')
    if path == '/fixtures/' and not isinstance(data, list):
        raise RuntimeError('Fixture response is not a list')
    with _cache_lock:
        _cache[path] = {'data': data, 'at': now}
    if path in ('/bootstrap-static/', '/fixtures/'):
        persist_snapshot('bootstrap' if path == '/bootstrap-static/' else 'fixtures', data, now, url)
    return data, False, now


def fetch_advanced_stats():
    if not ADVANCED_STATS_URL:
        return None, 'not_configured'
    now = time.time()
    with _cache_lock:
        if _advanced_cache['data'] is not None and now - _advanced_cache['at'] < CACHE_SECONDS:
            return _advanced_cache['data'], None
    if not ADVANCED_STATS_URL.lower().startswith('https://'):
        return None, 'Provider URL must use HTTPS.'
    headers = {'User-Agent': 'FPL-Brain-independent-prototype/0.3', 'Accept': 'application/json'}
    if ADVANCED_STATS_TOKEN:
        headers['Authorization'] = 'Bearer ' + ADVANCED_STATS_TOKEN
    req = Request(ADVANCED_STATS_URL, headers=headers)
    with urlopen(req, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError(f'Advanced stats provider returned HTTP {response.status}')
        payload = json.loads(response.read().decode('utf-8'))
    players = payload.get('players') if isinstance(payload, dict) else payload
    if not isinstance(players, list):
        raise RuntimeError('Provider response must be a list or an object containing a players array.')
    allowed = {'id','fpl_id','player_id','web_name','name','team','team_name','expected_goals','expected_assists','expected_goal_involvements','expected_goals_conceded','threat','creativity','influence','ict_index','shots','shots_on_target','big_chances','big_chances_created','key_passes','touches_in_box','defensive_contribution','clearances_blocks_interceptions','recoveries','tackles','interceptions','blocks','source'}
    clean = [{k: p[k] for k in allowed if k in p} for p in players if isinstance(p, dict)]
    now = time.time()
    data = {'players': clean, 'fetched_at_utc': utc_stamp(now), 'source': ADVANCED_STATS_URL}
    persist_snapshot('advanced', data, now, ADVANCED_STATS_URL)
    with _cache_lock:
        _advanced_cache['data'] = data
        _advanced_cache['at'] = now
    return data, None


def data_status():
    result = {'database': DB_PATH.name, 'advanced_stats_configured': bool(ADVANCED_STATS_URL), 'feeds': {}}
    for kind in ('bootstrap', 'fixtures', 'advanced'):
        snap = latest_snapshot(kind)
        try:
            with db_connect() as con:
                check = con.execute('SELECT last_success_at FROM feed_status WHERE kind=?', (kind,)).fetchone()
        except sqlite3.Error:
            check = None
        last_success = float(check['last_success_at']) if check else (snap['fetched_at'] if snap else None)
        result['feeds'][kind] = {'available': bool(snap), 'fetched_at_utc': utc_stamp(last_success) if last_success else None, 'last_changed_at_utc': utc_stamp(snap['fetched_at']) if snap else None, 'age_seconds': max(0, int(time.time()-last_success)) if last_success else None, 'source': snap['source'] if snap else None}
    return result


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
        try: n = int(self.headers.get('Content-Length', '0'))
        except ValueError: n = 0
        if n < 1 or n > MAX_BODY:
            raise ValueError('Request body must be between 1 byte and 64 KB')
        return json.loads(self.rfile.read(n).decode('utf-8'))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == '/api/health':
            self.send_json(200, {'ok': True, 'app': 'FPL Brain', 'version': '0.5', 'server_time_utc': utc_stamp(time.time()), 'ai_configured': bool(os.getenv('FPL_AI_API_KEY') and os.getenv('FPL_AI_MODEL')), 'advanced_stats_configured': bool(ADVANCED_STATS_URL), 'fpl_source': 'public FPL endpoint; undocumented and may change', 'data_pipeline': 'SQLite snapshots with stale-cache fallback'})
            return
        if path == '/api/data/status':
            self.send_json(200, {'ok': True, **data_status()})
            return
        if path == '/api/fpl/element-summary':
            qs = parse_qs(parsed.query)
            try: player_id = int(qs.get('id', ['0'])[0])
            except (TypeError, ValueError): player_id = 0
            if player_id < 1:
                self.send_json(400, {'ok': False, 'error': 'id must be a positive FPL element ID'})
                return
            try:
                data, cached, fetched_at = fetch_fpl(f'/element-summary/{player_id}/')
                self.send_json(200, {'ok': True, 'data': data, 'cached': cached, 'fetched_at_utc': utc_stamp(fetched_at), 'source': FPL_BASE + f'/element-summary/{player_id}/'})
            except (URLError, HTTPError, TimeoutError, RuntimeError, json.JSONDecodeError) as e:
                self.send_json(502, {'ok': False, 'error': 'Player history could not be retrieved.', 'detail': str(e)})
            return
        if path == '/api/fpl/history':
            qs = parse_qs(parsed.query)
            try: player_id = int(qs.get('player_id', ['0'])[0])
            except (TypeError, ValueError): player_id = 0
            try: limit = max(2, min(100, int(qs.get('limit', ['30'])[0])))
            except (TypeError, ValueError): limit = 30
            if player_id < 1:
                self.send_json(400, {'ok': False, 'error': 'player_id must be a positive FPL element ID'})
                return
            try:
                query = ('SELECT s.fetched_at,s.source,p.player_id,p.web_name,p.team_id,p.now_cost,p.total_points,p.minutes,p.form,p.expected_goals,p.expected_assists,p.expected_goal_involvements,p.expected_goals_conceded,p.ict_index,p.selected_by_percent '
                         'FROM player_snapshots p JOIN snapshots s ON s.id=p.snapshot_id WHERE p.player_id=? ORDER BY s.fetched_at DESC LIMIT ?')
                with db_connect() as con:
                    rows = con.execute(query, (player_id, limit)).fetchall()
                history = []
                for row in reversed(rows):
                    item = dict(row); item['fetched_at_utc'] = utc_stamp(item['fetched_at']); history.append(item)
                self.send_json(200, {'ok': True, 'player_id': player_id, 'count': len(history), 'history': history})
            except sqlite3.Error as e:
                self.send_json(500, {'ok': False, 'error': 'Could not read player history', 'detail': str(e)})
            return
        if path == '/api/fpl/advanced-stats':
            try:
                data, error = fetch_advanced_stats()
                if error == 'not_configured':
                    cached = latest_snapshot('advanced')
                    if cached:
                        self.send_json(200, {'ok': True, 'configured': False, 'stale': True, 'data': cached['data'], 'fetched_at_utc': utc_stamp(cached['fetched_at']), 'source': cached['source'], 'notice': 'Returning last stored provider snapshot; provider is not configured now.'})
                    else:
                        self.send_json(200, {'ok': True, 'configured': False, 'stale': False, 'data': {'players': []}, 'fetched_at_utc': None, 'source': None, 'notice': 'No advanced stats provider configured; no values are fabricated.'})
                    return
                if error:
                    raise RuntimeError(error)
                self.send_json(200, {'ok': True, 'configured': True, 'stale': False, 'data': data, 'source': data.get('source'), 'fetched_at_utc': data.get('fetched_at_utc')})
            except (URLError, HTTPError, TimeoutError, RuntimeError, json.JSONDecodeError) as e:
                cached = latest_snapshot('advanced')
                if cached:
                    self.send_json(200, {'ok': True, 'configured': True, 'stale': True, 'data': cached['data'], 'fetched_at_utc': utc_stamp(cached['fetched_at']), 'source': cached['source'], 'warning': str(e)})
                else:
                    self.send_json(502, {'ok': False, 'error': 'Advanced stats provider request failed.', 'detail': str(e), 'configured': True})
            return
        if path in ('/api/fpl/bootstrap', '/api/fpl/fixtures'):
            upstream_path = '/bootstrap-static/' if path.endswith('bootstrap') else '/fixtures/'
            kind = 'bootstrap' if upstream_path == '/bootstrap-static/' else 'fixtures'
            try:
                data, cached, fetched_at = fetch_fpl(upstream_path)
                self.send_json(200, {'ok': True, 'data': data, 'cached': cached, 'stale': False, 'fetched_at_utc': utc_stamp(fetched_at), 'source': FPL_BASE + upstream_path, 'notice': 'Public endpoint is undocumented, can change, and availability is not guaranteed.'})
            except (URLError, HTTPError, TimeoutError, RuntimeError, json.JSONDecodeError, sqlite3.Error) as e:
                stale = latest_snapshot(kind)
                if stale:
                    self.send_json(200, {'ok': True, 'data': stale['data'], 'cached': True, 'stale': True, 'fetched_at_utc': utc_stamp(stale['fetched_at']), 'source': stale['source'], 'warning': str(e), 'notice': 'Live upstream failed; showing the last successfully stored snapshot.'})
                else:
                    self.send_json(502, {'ok': False, 'error': 'Live FPL data could not be retrieved and no cached snapshot exists.', 'detail': str(e), 'source': 'https://fantasy.premierleague.com/', 'cached_data_available': False, 'notice': 'No live data was supplied. Check internet access and try again later.'})
            return
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path != '/api/ai/chat':
            self.send_json(404, {'ok': False, 'error': 'Unknown API route'}); return
        api_key = os.getenv('FPL_AI_API_KEY', '').strip()
        model = os.getenv('FPL_AI_MODEL', '').strip()
        base_url = os.getenv('FPL_AI_BASE_URL', 'https://api.openai.com/v1').strip().rstrip('/')
        if not api_key or not model:
            self.send_json(503, {'ok': False, 'error': 'AI provider is not configured.', 'detail': 'Set FPL_AI_API_KEY and FPL_AI_MODEL in your server environment. No key is stored in the browser.'}); return
        try:
            body = self.read_body(); messages = body.get('messages', [])
            if not isinstance(messages, list) or not messages or len(messages) > 20:
                raise ValueError('Provide 1–20 chat messages')
            safe_messages = []
            for msg in messages:
                if isinstance(msg, dict) and msg.get('role') in ('system', 'user', 'assistant') and isinstance(msg.get('content', ''), str):
                    safe_messages.append({'role': msg['role'], 'content': msg['content'][:8000]})
            payload = json_bytes({'model': model, 'messages': safe_messages, 'temperature': 0.2})
            req = Request(base_url + '/chat/completions', data=payload, method='POST', headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json', 'Accept': 'application/json'})
            with urlopen(req, timeout=35) as response:
                result = json.loads(response.read().decode('utf-8'))
            answer = result.get('choices', [{}])[0].get('message', {}).get('content', '')
            if not isinstance(answer, str) or not answer:
                raise RuntimeError('AI provider returned no message text')
            self.send_json(200, {'ok': True, 'answer': answer, 'model': model})
        except ValueError as e:
            self.send_json(400, {'ok': False, 'error': str(e)})
        except (URLError, HTTPError, TimeoutError, RuntimeError, json.JSONDecodeError, IndexError, KeyError) as e:
            self.send_json(502, {'ok': False, 'error': 'AI provider request failed.', 'detail': str(e)})


try:
    init_db()
except (OSError, sqlite3.Error) as db_error:
    print('[FPL Brain] Warning: persistent data store unavailable:', db_error)


def main():
    init_db()
    print(f'FPL Brain v0.5: http://{HOST}:{PORT}')
    print(f'Data snapshots: {DB_PATH}')
    print('Stale data is labelled, never presented as fresh.')
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

if __name__ == '__main__':
    main()
