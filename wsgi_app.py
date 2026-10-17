"""WSGI adapter for PythonAnywhere and other WSGI hosts.

Import as `from wsgi_app import application`. This reuses the same cache,
SQLite snapshot store, schema checks, and optional provider configuration as
server.py without starting a separate HTTP server.
"""
import json
import os
import time
from pathlib import Path
from urllib.parse import parse_qs
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import server as core

ROOT = Path(__file__).resolve().parent


def _json_response(start_response, status, payload):
    body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    start_response(status, [('Content-Type', 'application/json; charset=utf-8'), ('Content-Length', str(len(body))), ('Cache-Control', 'no-store')])
    return [body]


def _body(environ):
    try:
        length = int(environ.get('CONTENT_LENGTH') or '0')
    except ValueError:
        length = 0
    if length < 1 or length > core.MAX_BODY:
        raise ValueError('Request body must be between 1 byte and 64 KB')
    return json.loads(environ['wsgi.input'].read(length).decode('utf-8'))


def application(environ, start_response):
    path = environ.get('PATH_INFO', '/') or '/'
    method = environ.get('REQUEST_METHOD', 'GET').upper()
    if method == 'GET' and path in ('/', '/index.html'):
        try:
            body = (ROOT / 'index.html').read_bytes()
            start_response('200 OK', [('Content-Type', 'text/html; charset=utf-8'), ('Content-Length', str(len(body))), ('Cache-Control', 'no-cache')])
            return [body]
        except OSError:
            return _json_response(start_response, '500 Internal Server Error', {'ok': False, 'error': 'index.html is missing from the project directory'})

    if method == 'GET' and path == '/api/health':
        return _json_response(start_response, '200 OK', {'ok': True, 'app': 'FPL Brain', 'version': '0.5', 'server_time_utc': core.utc_stamp(time.time()), 'ai_configured': bool(os.getenv('FPL_AI_API_KEY') and os.getenv('FPL_AI_MODEL')), 'advanced_stats_configured': bool(core.ADVANCED_STATS_URL), 'fpl_source': 'public FPL endpoint; undocumented and may change', 'data_pipeline': 'SQLite snapshots with stale-cache fallback'})

    if method == 'GET' and path == '/api/data/status':
        return _json_response(start_response, '200 OK', {'ok': True, **core.data_status()})

    if method == 'GET' and path in ('/api/fpl/bootstrap', '/api/fpl/fixtures'):
        upstream_path = '/bootstrap-static/' if path.endswith('bootstrap') else '/fixtures/'
        kind = 'bootstrap' if upstream_path == '/bootstrap-static/' else 'fixtures'
        try:
            data, cached, fetched_at = core.fetch_fpl(upstream_path)
            return _json_response(start_response, '200 OK', {'ok': True, 'data': data, 'cached': cached, 'stale': False, 'fetched_at_utc': core.utc_stamp(fetched_at), 'source': core.FPL_BASE + upstream_path, 'notice': 'Public endpoint is undocumented, can change, and availability is not guaranteed.'})
        except (URLError, HTTPError, TimeoutError, RuntimeError, json.JSONDecodeError, OSError) as exc:
            cached = core.latest_snapshot(kind)
            if cached:
                return _json_response(start_response, '200 OK', {'ok': True, 'data': cached['data'], 'cached': True, 'stale': True, 'fetched_at_utc': core.utc_stamp(cached['fetched_at']), 'source': cached['source'], 'warning': str(exc), 'notice': 'Live upstream failed; showing the last successfully stored snapshot.'})
            return _json_response(start_response, '502 Bad Gateway', {'ok': False, 'error': 'Live FPL data could not be retrieved and no cached snapshot exists.', 'detail': str(exc), 'cached_data_available': False})

    if method == 'GET' and path == '/api/fpl/element-summary':
        qs = parse_qs(environ.get('QUERY_STRING', ''))
        try:
            player_id = int(qs.get('id', ['0'])[0])
        except (TypeError, ValueError):
            player_id = 0
        if player_id < 1:
            return _json_response(start_response, '400 Bad Request', {'ok': False, 'error': 'id must be a positive FPL element ID'})
        try:
            data, cached, fetched_at = core.fetch_fpl(f'/element-summary/{player_id}/')
            return _json_response(start_response, '200 OK', {'ok': True, 'data': data, 'cached': cached, 'fetched_at_utc': core.utc_stamp(fetched_at), 'source': core.FPL_BASE + f'/element-summary/{player_id}/'})
        except (URLError, HTTPError, TimeoutError, RuntimeError, json.JSONDecodeError, OSError) as exc:
            return _json_response(start_response, '502 Bad Gateway', {'ok': False, 'error': 'Player history could not be retrieved.', 'detail': str(exc)})

    if method == 'GET' and path == '/api/fpl/history':
        qs = parse_qs(environ.get('QUERY_STRING', ''))
        try:
            player_id = int(qs.get('player_id', ['0'])[0]); limit = max(2, min(100, int(qs.get('limit', ['30'])[0])))
        except (TypeError, ValueError):
            return _json_response(start_response, '400 Bad Request', {'ok': False, 'error': 'player_id must be a positive FPL element ID and limit must be numeric'})
        if player_id < 1:
            return _json_response(start_response, '400 Bad Request', {'ok': False, 'error': 'player_id must be a positive FPL element ID'})
        query = ('SELECT s.fetched_at,s.source,p.player_id,p.web_name,p.team_id,p.now_cost,p.total_points,p.minutes,p.form,p.expected_goals,p.expected_assists,p.expected_goal_involvements,p.expected_goals_conceded,p.ict_index,p.selected_by_percent '
                 'FROM player_snapshots p JOIN snapshots s ON s.id=p.snapshot_id WHERE p.player_id=? ORDER BY s.fetched_at DESC LIMIT ?')
        try:
            with core.db_connect() as con:
                rows = con.execute(query, (player_id, limit)).fetchall()
            history = []
            for row in reversed(rows):
                item = dict(row); item['fetched_at_utc'] = core.utc_stamp(item['fetched_at']); history.append(item)
            return _json_response(start_response, '200 OK', {'ok': True, 'player_id': player_id, 'count': len(history), 'history': history})
        except Exception as exc:
            return _json_response(start_response, '500 Internal Server Error', {'ok': False, 'error': 'Could not read player history', 'detail': str(exc)})

    if method == 'GET' and path == '/api/fpl/advanced-stats':
        try:
            data, error = core.fetch_advanced_stats()
            if error == 'not_configured':
                cached = core.latest_snapshot('advanced')
                if cached:
                    return _json_response(start_response, '200 OK', {'ok': True, 'configured': False, 'stale': True, 'data': cached['data'], 'fetched_at_utc': core.utc_stamp(cached['fetched_at']), 'source': cached['source'], 'notice': 'Returning last stored provider snapshot; provider is not configured now.'})
                return _json_response(start_response, '200 OK', {'ok': True, 'configured': False, 'stale': False, 'data': {'players': []}, 'fetched_at_utc': None, 'source': None, 'notice': 'No advanced stats provider configured; no values are fabricated.'})
            if error:
                raise RuntimeError(error)
            return _json_response(start_response, '200 OK', {'ok': True, 'configured': True, 'stale': False, 'data': data, 'source': data.get('source'), 'fetched_at_utc': data.get('fetched_at_utc')})
        except (URLError, HTTPError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
            cached = core.latest_snapshot('advanced')
            if cached:
                return _json_response(start_response, '200 OK', {'ok': True, 'configured': True, 'stale': True, 'data': cached['data'], 'fetched_at_utc': core.utc_stamp(cached['fetched_at']), 'source': cached['source'], 'warning': str(exc)})
            return _json_response(start_response, '502 Bad Gateway', {'ok': False, 'error': 'Advanced stats provider request failed.', 'detail': str(exc), 'configured': True})

    if method == 'POST' and path == '/api/ai/chat':
        api_key = os.getenv('FPL_AI_API_KEY', '').strip(); model = os.getenv('FPL_AI_MODEL', '').strip(); base = os.getenv('FPL_AI_BASE_URL', 'https://api.openai.com/v1').strip().rstrip('/')
        if not api_key or not model:
            return _json_response(start_response, '503 Service Unavailable', {'ok': False, 'error': 'AI provider is not configured.', 'detail': 'Set FPL_AI_API_KEY and FPL_AI_MODEL in the server environment.'})
        try:
            body = _body(environ); messages = body.get('messages', [])
            if not isinstance(messages, list) or not messages or len(messages) > 20:
                raise ValueError('Provide 1–20 chat messages')
            safe = [{'role': m['role'], 'content': m['content'][:8000]} for m in messages if isinstance(m, dict) and m.get('role') in ('system', 'user', 'assistant') and isinstance(m.get('content', ''), str)]
            req = Request(base + '/chat/completions', data=core.json_bytes({'model': model, 'messages': safe, 'temperature': 0.2}), method='POST', headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json', 'Accept': 'application/json'})
            with urlopen(req, timeout=35) as response:
                result = json.loads(response.read().decode('utf-8'))
            answer = result.get('choices', [{}])[0].get('message', {}).get('content', '')
            if not isinstance(answer, str) or not answer:
                raise RuntimeError('AI provider returned no message text')
            return _json_response(start_response, '200 OK', {'ok': True, 'answer': answer, 'model': model})
        except ValueError as exc:
            return _json_response(start_response, '400 Bad Request', {'ok': False, 'error': str(exc)})
        except (URLError, HTTPError, TimeoutError, RuntimeError, json.JSONDecodeError, IndexError, KeyError) as exc:
            return _json_response(start_response, '502 Bad Gateway', {'ok': False, 'error': 'AI provider request failed.', 'detail': str(exc)})

    return _json_response(start_response, '404 Not Found', {'ok': False, 'error': 'Not found'})
