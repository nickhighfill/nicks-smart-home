from flask import Flask, jsonify, request, send_from_directory, redirect
import pychromecast
import requests as http_requests
import time
import threading
import json
import os
import base64
from urllib.parse import urlencode
from spotify_controller import SpotifyController

app = Flask(__name__)

# ===== SPEAKER CONFIG =====
KNOWN_SPEAKERS = [
    {'id': 'kitchen', 'name': 'Kitchen speaker', 'ip': '192.168.1.110'},
    {'id': 'bedroom', 'name': 'Master Bedroom speaker', 'ip': '192.168.1.157'},
    {'id': 'office', 'name': 'Office', 'ip': '192.168.1.36'},
]

speakers = {}
browser = None
everywhere_group = None

EVERYWHERE_GROUP_NAME = 'Everywhere'

def init_speakers():
    global speakers, browser, everywhere_group
    try:
        all_names = [s['name'] for s in KNOWN_SPEAKERS] + [EVERYWHERE_GROUP_NAME]
        all_hosts = [s['ip'] for s in KNOWN_SPEAKERS]
        chromecasts, browser = pychromecast.get_listed_chromecasts(
            friendly_names=all_names,
            known_hosts=all_hosts
        )
        time.sleep(8)
        for cc in chromecasts:
            cc.wait(timeout=10)
            if cc.name == EVERYWHERE_GROUP_NAME:
                everywhere_group = cc
                print(f"Found Everywhere group")
                continue
            for s in KNOWN_SPEAKERS:
                if cc.name == s['name']:
                    speakers[s['id']] = cc
                    break
        print(f"Connected to {len(speakers)} speakers")
    except Exception as e:
        print(f"Speaker connection error: {e}")

threading.Thread(target=init_speakers, daemon=True).start()

# ===== SPOTIFY CONFIG =====
SPOTIFY_CLIENT_ID = 'b493ef178ca84f5d96df3d3e471360b4'
SPOTIFY_CLIENT_SECRET = '36b5fa71c1f340738eb8bc717cfb67ce'
SPOTIFY_REDIRECT_URI = 'https://nickhighfill.com/callback'
SPOTIFY_SCOPES = 'user-read-playback-state user-modify-playback-state user-read-currently-playing playlist-read-private playlist-read-collaborative'

TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.spotify_tokens.json')
spotify_tokens = {}

def load_tokens():
    global spotify_tokens
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            spotify_tokens = json.load(f)

def save_tokens():
    with open(TOKEN_FILE, 'w') as f:
        json.dump(spotify_tokens, f)

def get_spotify_token():
    if not spotify_tokens.get('access_token'):
        load_tokens()
    if spotify_tokens.get('expires_at', 0) < time.time() + 60:
        if spotify_tokens.get('refresh_token'):
            refresh_spotify_token()
    return spotify_tokens.get('access_token')

def refresh_spotify_token():
    auth = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    r = http_requests.post('https://accounts.spotify.com/api/token', data={
        'grant_type': 'refresh_token',
        'refresh_token': spotify_tokens['refresh_token']
    }, headers={'Authorization': f'Basic {auth}'})
    data = r.json()
    if 'access_token' in data:
        spotify_tokens['access_token'] = data['access_token']
        spotify_tokens['expires_at'] = time.time() + data.get('expires_in', 3600)
        if 'refresh_token' in data:
            spotify_tokens['refresh_token'] = data['refresh_token']
        save_tokens()

def spotify_api(path, method='GET', body=None):
    token = get_spotify_token()
    if not token:
        return None
    headers = {'Authorization': f'Bearer {token}'}
    url = f'https://api.spotify.com/v1{path}'
    if method == 'GET':
        r = http_requests.get(url, headers=headers)
    elif method == 'PUT':
        r = http_requests.put(url, headers=headers, json=body)
    elif method == 'POST':
        r = http_requests.post(url, headers=headers, json=body)
    else:
        return None
    if r.status_code == 204:
        return {'ok': True}
    if r.status_code == 401:
        refresh_spotify_token()
        return spotify_api(path, method, body)
    try:
        return r.json()
    except:
        return {'ok': True, 'status': r.status_code}

load_tokens()

# ===== ROUTES: STATIC =====
@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')

# ===== ROUTES: SPEAKERS =====
@app.route('/api/speakers')
def get_speakers():
    result = []
    for info in KNOWN_SPEAKERS:
        sid = info['id']
        cc = speakers.get(sid)
        entry = {
            'id': sid,
            'name': info['name'],
            'ip': info['ip'],
            'connected': cc is not None,
        }
        if cc:
            try:
                entry['volume'] = round(cc.status.volume_level * 100)
                entry['muted'] = cc.status.volume_muted
                entry['app'] = cc.status.display_name or None
                entry['is_idle'] = cc.status.display_name is None
                mc = cc.media_controller
                if mc.status and mc.status.player_state:
                    entry['player_state'] = mc.status.player_state
                    entry['title'] = getattr(mc.status, 'title', None)
                    entry['artist'] = getattr(mc.status, 'artist', None)
            except Exception as e:
                entry['error'] = str(e)
        result.append(entry)
    return jsonify(result)

@app.route('/api/speakers/<sid>/volume', methods=['POST'])
def set_volume(sid):
    level = request.json.get('level', 50)
    targets = list(speakers.values()) if sid == 'all' else [speakers.get(sid)]
    for cc in targets:
        if cc:
            cc.set_volume(level / 100.0)
    return jsonify({'ok': True})

@app.route('/api/speakers/cast', methods=['POST'])
def cast_audio():
    data = request.json
    url = data['url']
    content_type = data.get('content_type', 'audio/mpeg')
    title = data.get('title', 'Stream')
    target_ids = data.get('speakers', list(speakers.keys()))
    for sid in target_ids:
        cc = speakers.get(sid)
        if cc:
            mc = cc.media_controller
            mc.play_media(url, content_type, title=title)
            mc.block_until_active(timeout=10)
    return jsonify({'ok': True})

@app.route('/api/speakers/<sid>/stop', methods=['POST'])
def stop_speaker(sid):
    targets = list(speakers.values()) if sid == 'all' else [speakers.get(sid)]
    for cc in targets:
        if cc:
            try:
                cc.media_controller.stop()
            except:
                pass
    return jsonify({'ok': True})

@app.route('/api/speakers/<sid>/pause', methods=['POST'])
def pause_speaker(sid):
    targets = list(speakers.values()) if sid == 'all' else [speakers.get(sid)]
    for cc in targets:
        if cc:
            try:
                cc.media_controller.pause()
            except:
                pass
    return jsonify({'ok': True})

@app.route('/api/speakers/<sid>/play', methods=['POST'])
def play_speaker(sid):
    targets = list(speakers.values()) if sid == 'all' else [speakers.get(sid)]
    for cc in targets:
        if cc:
            try:
                cc.media_controller.play()
            except:
                pass
    return jsonify({'ok': True})

# ===== ROUTES: SPOTIFY AUTH =====
@app.route('/spotify/login')
def spotify_login():
    params = urlencode({
        'client_id': SPOTIFY_CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': SPOTIFY_REDIRECT_URI,
        'scope': SPOTIFY_SCOPES,
    })
    return redirect(f'https://accounts.spotify.com/authorize?{params}')

@app.route('/callback')
def spotify_callback():
    code = request.args.get('code')
    error = request.args.get('error')
    if error:
        return redirect('/')
    auth = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    r = http_requests.post('https://accounts.spotify.com/api/token', data={
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': SPOTIFY_REDIRECT_URI,
    }, headers={'Authorization': f'Basic {auth}'})
    data = r.json()
    if 'access_token' in data:
        spotify_tokens['access_token'] = data['access_token']
        spotify_tokens['refresh_token'] = data.get('refresh_token')
        spotify_tokens['expires_at'] = time.time() + data.get('expires_in', 3600)
        save_tokens()
    return redirect('/')

@app.route('/api/spotify/manual-callback', methods=['POST'])
def spotify_manual_callback():
    url = request.json.get('url', '')
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    code = params.get('code', [None])[0]
    if not code:
        return jsonify({'error': 'No code found in URL'}), 400
    auth = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    r = http_requests.post('https://accounts.spotify.com/api/token', data={
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': SPOTIFY_REDIRECT_URI,
    }, headers={'Authorization': f'Basic {auth}'})
    data = r.json()
    if 'access_token' in data:
        spotify_tokens['access_token'] = data['access_token']
        spotify_tokens['refresh_token'] = data.get('refresh_token')
        spotify_tokens['expires_at'] = time.time() + data.get('expires_in', 3600)
        save_tokens()
        return jsonify({'ok': True})
    return jsonify({'error': data.get('error_description', 'Token exchange failed')}), 400

# ===== ROUTES: SPOTIFY API =====
@app.route('/api/spotify/status')
def spotify_status():
    token = get_spotify_token()
    return jsonify({'connected': token is not None})

@app.route('/api/spotify/player')
def spotify_player():
    data = spotify_api('/me/player')
    if not data:
        return jsonify({'is_playing': False})
    return jsonify(data)

@app.route('/api/spotify/playlists')
def spotify_playlists():
    data = spotify_api('/me/playlists?limit=30')
    return jsonify(data or {'items': []})

@app.route('/api/spotify/devices')
def spotify_devices():
    data = spotify_api('/me/player/devices')
    devices = data.get('devices', []) if data else []
    # Always include Everywhere if we have the Cast group connected
    if everywhere_group:
        has_everywhere = any(d['name'] == EVERYWHERE_GROUP_NAME for d in devices)
        if not has_everywhere:
            devices.append({
                'id': 'everywhere_cast',
                'is_active': False,
                'is_private_session': False,
                'is_restricted': False,
                'name': EVERYWHERE_GROUP_NAME,
                'supports_volume': True,
                'type': 'CastAudio',
                'volume_percent': 50,
                '_cast_group': True
            })
    return jsonify({'devices': devices})

PREFERRED_DEVICE_NAME = 'Everywhere'

spotify_ctrl = None

def launch_spotify_on_cast():
    """Launch the Spotify app on the Everywhere Cast group."""
    global spotify_ctrl
    if not everywhere_group:
        print("No Everywhere group connected")
        return False
    try:
        if spotify_ctrl is None:
            spotify_ctrl = SpotifyController(everywhere_group)
            everywhere_group.register_handler(spotify_ctrl)
        launched = spotify_ctrl.launch_app(timeout=15)
        print(f"Spotify app launch: {launched}")
        return launched
    except Exception as e:
        print(f"SpotifyController error: {e}")
        import traceback
        traceback.print_exc()
        return False

def wait_for_everywhere(max_wait=20):
    """Poll Spotify API until Everywhere appears, return its device ID."""
    for i in range(max_wait // 2):
        devices = spotify_api('/me/player/devices')
        if devices and devices.get('devices'):
            for d in devices['devices']:
                if d['name'] == PREFERRED_DEVICE_NAME:
                    print(f"Everywhere found in API after {i*2}s: {d['id']}")
                    return d['id']
        time.sleep(2)
    return None

def find_preferred_device():
    """Find the Everywhere speaker group, launching Spotify on it if needed."""
    # First check if it's already visible
    devices = spotify_api('/me/player/devices')
    if devices and devices.get('devices'):
        for d in devices['devices']:
            if d['name'] == PREFERRED_DEVICE_NAME:
                return d['id']
    # Launch Spotify on the Cast group and wait for it
    if launch_spotify_on_cast():
        device_id = wait_for_everywhere()
        if device_id:
            return device_id
    # Fall back to any active device
    devices = spotify_api('/me/player/devices')
    if devices and devices.get('devices'):
        for d in devices['devices']:
            if d['is_active']:
                return d['id']
    return None

@app.route('/api/spotify/play', methods=['PUT'])
def spotify_play():
    data = request.json or {}
    device_id = data.get('device_id')
    if device_id == 'everywhere_cast':
        device_id = resolve_everywhere_id()
    if not device_id:
        device_id = find_preferred_device()
    path = '/me/player/play'
    if device_id:
        path += f'?device_id={device_id}'
    body = {}
    if 'context_uri' in data:
        body['context_uri'] = data['context_uri']
    if 'uris' in data:
        body['uris'] = data['uris']
    if 'offset' in data:
        body['offset'] = data['offset']
    result = spotify_api(path, 'PUT', body if body else None)
    return jsonify(result or {'ok': True})

@app.route('/api/spotify/pause', methods=['PUT'])
def spotify_pause():
    result = spotify_api('/me/player/pause', 'PUT')
    return jsonify(result or {'ok': True})

@app.route('/api/spotify/next', methods=['POST'])
def spotify_next():
    result = spotify_api('/me/player/next', 'POST')
    return jsonify(result or {'ok': True})

@app.route('/api/spotify/previous', methods=['POST'])
def spotify_previous():
    result = spotify_api('/me/player/previous', 'POST')
    return jsonify(result or {'ok': True})

@app.route('/api/spotify/shuffle', methods=['PUT'])
def spotify_shuffle():
    state = request.json.get('state', True)
    result = spotify_api(f'/me/player/shuffle?state={str(state).lower()}', 'PUT')
    return jsonify(result or {'ok': True})

def resolve_everywhere_id():
    """Launch Spotify on the Everywhere group and get its real device ID."""
    # Check API first
    devices = spotify_api('/me/player/devices')
    if devices and devices.get('devices'):
        for d in devices['devices']:
            if d['name'] == EVERYWHERE_GROUP_NAME:
                return d['id']
    # Launch Spotify app and wait for it to register
    if launch_spotify_on_cast():
        device_id = wait_for_everywhere()
        if device_id:
            return device_id
    print("Could not resolve Everywhere device ID")
    return None

@app.route('/api/spotify/transfer', methods=['PUT'])
def spotify_transfer():
    data = request.json
    device_ids = data.get('device_ids', [])
    # Resolve our fake cast ID to a real Spotify device ID
    if 'everywhere_cast' in device_ids:
        real_id = resolve_everywhere_id()
        if real_id:
            device_ids = [real_id]
            print(f"Transferring to Everywhere with device ID: {real_id}")
        else:
            return jsonify({'error': 'Could not wake Everywhere group'}), 500
    result = spotify_api('/me/player', 'PUT', {'device_ids': device_ids, 'play': True})
    print(f"Transfer result: {result}")
    return jsonify(result or {'ok': True})

@app.route('/api/circadian-brightness', methods=['POST'])
def save_circadian_brightness():
    data = request.json
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.circadian_brightness.json')
    with open(path, 'w') as f:
        json.dump(data, f)
    return jsonify({'ok': True})

if __name__ == '__main__':
    print("Nick's Smart Home server starting on http://localhost:8080")
    app.run(host='0.0.0.0', port=8080, debug=False)
