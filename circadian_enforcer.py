#!/usr/bin/env python3
"""Circadian Enforcer — runs on the Pi and corrects light colors every 10 seconds."""

import time
import json
import os
import urllib.request
from datetime import datetime

BRIDGE = 'http://192.168.0.2'
API_KEY = 'v-I9tLBE0xEPKGNWMMqihE1YpzArq9eviFkA7SOZ'
API = f'{BRIDGE}/api/{API_KEY}'

CIRCADIAN_STEPS = [
    {'time': '05:00', 'ct': 357, 'bri': 150},
    {'time': '06:00', 'ct': 312, 'bri': 254},
    {'time': '07:00', 'ct': 250, 'bri': 254},
    {'time': '08:00', 'ct': 208, 'bri': 254},
    {'time': '09:30', 'ct': 179, 'bri': 254},
    {'time': '12:00', 'ct': 154, 'bri': 254},
    {'time': '15:00', 'ct': 182, 'bri': 254},
    {'time': '17:00', 'ct': 222, 'bri': 254},
    {'time': '18:30', 'ct': 263, 'bri': 254},
    {'time': '19:30', 'ct': 312, 'bri': 254},
    {'time': '20:15', 'ct': 370, 'bri': 254},
    {'time': '20:50', 'ct': 400, 'bri': 220},
    {'time': '21:15', 'ct': 440, 'bri': 150},
    {'time': '22:00', 'ct': 480, 'bri': 80},
    {'time': '23:00', 'ct': 500, 'bri': 30},
]

CT_TOLERANCE = 15
CHECK_INTERVAL = 10
DRIFT_INTERVAL = 900  # Only correct already-on lights every 15 minutes
DRIFT_TRANSITION = 9000  # 15-minute slow transition (in 1/10s units) so changes are imperceptible
BRIGHTNESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.circadian_brightness.json')

prev_light_states = {}
last_drift_correction = 0  # timestamp of last drift correction for already-on lights


room_overrides = {}

def load_custom_brightness():
    """Load custom brightness overrides saved from the dashboard."""
    global room_overrides
    try:
        if os.path.exists(BRIGHTNESS_FILE):
            with open(BRIGHTNESS_FILE) as f:
                custom = json.load(f)
            master = custom.get('master', custom)
            room_overrides = custom.get('overrides', {})
            for step in CIRCADIAN_STEPS:
                if step['time'] in master:
                    step['bri'] = master[step['time']]
    except Exception:
        pass


def step_to_mins(step):
    h, m = map(int, step['time'].split(':'))
    return h * 60 + m


def get_circadian_now():
    now = datetime.now()
    mins = now.hour * 60 + now.minute

    prev_idx = len(CIRCADIAN_STEPS) - 1
    next_idx = 0
    for i, step in enumerate(CIRCADIAN_STEPS):
        if mins < step_to_mins(step):
            next_idx = i
            prev_idx = i - 1 if i > 0 else len(CIRCADIAN_STEPS) - 1
            break
        if i == len(CIRCADIAN_STEPS) - 1:
            prev_idx = i
            next_idx = 0

    prev_step = CIRCADIAN_STEPS[prev_idx]
    next_step = CIRCADIAN_STEPS[next_idx]
    prev_mins = step_to_mins(prev_step)
    next_mins = step_to_mins(next_step)
    if next_mins <= prev_mins:
        next_mins += 1440
    current_mins = mins
    if current_mins < prev_mins:
        current_mins += 1440

    rng = next_mins - prev_mins
    progress = (current_mins - prev_mins) / rng if rng > 0 else 0

    ct = round(prev_step['ct'] + (next_step['ct'] - prev_step['ct']) * progress)
    bri = round(prev_step['bri'] + (next_step['bri'] - prev_step['bri']) * progress)
    return ct, bri, prev_step, next_step, progress, prev_idx


def api_get(path):
    req = urllib.request.Request(f'{API}{path}')
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def api_put(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(f'{API}{path}', data=data, method='PUT')
    req.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def check_circadian_enabled():
    schedules = api_get('/schedules')
    for sid, s in schedules.items():
        if s.get('name', '').startswith('Circadian:') and s.get('status') == 'enabled':
            return True
    return False


def get_effective_room_on(gid, up_to_idx):
    """Walk backwards through steps to find the most recent on/off state for a room."""
    for i in range(up_to_idx, -1, -1):
        time = CIRCADIAN_STEPS[i]['time']
        ov = room_overrides.get(time, {}).get(gid)
        if isinstance(ov, dict) and 'on' in ov:
            return ov['on']
    return True


def get_room_override(gid, target_bri, prev_step, next_step, progress, prev_idx):
    """Get brightness and on/off for a specific room, applying overrides if set."""
    # Check cascading on/off state
    if not get_effective_room_on(gid, prev_idx):
        return target_bri, False

    # Handle brightness overrides
    prev_ov = room_overrides.get(prev_step['time'], {}).get(gid)
    next_ov = room_overrides.get(next_step['time'], {}).get(gid)

    prev_bri_ov = None
    next_bri_ov = None
    if isinstance(prev_ov, dict):
        prev_bri_ov = prev_ov.get('bri')
    elif isinstance(prev_ov, (int, float)):
        prev_bri_ov = prev_ov
    if isinstance(next_ov, dict):
        next_bri_ov = next_ov.get('bri')
    elif isinstance(next_ov, (int, float)):
        next_bri_ov = next_ov

    if prev_bri_ov is not None or next_bri_ov is not None:
        prev_bri = prev_bri_ov if prev_bri_ov is not None else prev_step['bri']
        next_bri = next_bri_ov if next_bri_ov is not None else next_step['bri']
        return round(prev_bri + (next_bri - prev_bri) * progress), True
    return target_bri, True


def enforce():
    global prev_light_states, last_drift_correction

    target_ct, target_bri, prev_step, next_step, progress, prev_idx = get_circadian_now()
    lights = api_get('/lights')
    groups = api_get('/groups')

    now = time.time()
    do_drift = (now - last_drift_correction) >= DRIFT_INTERVAL

    for gid, group in groups.items():
        if group.get('type') != 'Room' or not group.get('lights'):
            continue
        if not group.get('state', {}).get('any_on'):
            continue

        room_bri, room_on = get_room_override(gid, target_bri, prev_step, next_step, progress, prev_idx)

        if not room_on:
            continue

        any_just_on = False
        any_ct_off = False
        for lid in group['lights']:
            light = lights.get(lid)
            if not light or not light.get('state', {}).get('on'):
                continue

            was_off = prev_light_states.get(lid) is False or lid not in prev_light_states
            ct_off = abs((light['state'].get('ct', 0)) - target_ct) > CT_TOLERANCE

            if was_off:
                any_just_on = True
            if ct_off:
                any_ct_off = True

        if any_just_on:
            # Light just turned on — set both ct and bri immediately
            api_put(f'/groups/{gid}/action', {'ct': target_ct, 'bri': room_bri, 'transitiontime': 30})
        elif any_ct_off and do_drift:
            # Already-on light drifted — correct with slow transition (only every 15 min)
            api_put(f'/groups/{gid}/action', {'ct': target_ct, 'transitiontime': DRIFT_TRANSITION})

    if do_drift:
        last_drift_correction = now

    prev_light_states = {lid: light['state']['on'] for lid, light in lights.items()}


def main():
    print(f'Circadian Enforcer started — checking every {CHECK_INTERVAL}s')
    load_custom_brightness()

    while True:
        try:
            load_custom_brightness()
            if check_circadian_enabled():
                enforce()
                ct, bri, _, _, _, _ = get_circadian_now()
        except Exception as e:
            print(f'Error: {e}')

        time.sleep(CHECK_INTERVAL)


if __name__ == '__main__':
    main()
