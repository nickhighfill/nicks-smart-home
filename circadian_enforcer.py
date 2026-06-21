#!/usr/bin/env python3
"""Circadian Enforcer — runs on the Pi and corrects light colors every 10 seconds."""

import time
import json
import urllib.request
from datetime import datetime

BRIDGE = 'http://192.168.0.2'
API_KEY = 'v-I9tLBE0xEPKGNWMMqihE1YpzArq9eviFkA7SOZ'
API = f'{BRIDGE}/api/{API_KEY}'

CIRCADIAN_STEPS = [
    {'time': '06:00', 'ct': 400, 'bri': 254},
    {'time': '07:00', 'ct': 320, 'bri': 254},
    {'time': '08:00', 'ct': 250, 'bri': 254},
    {'time': '09:30', 'ct': 185, 'bri': 254},
    {'time': '12:00', 'ct': 160, 'bri': 254},
    {'time': '15:00', 'ct': 200, 'bri': 254},
    {'time': '17:00', 'ct': 280, 'bri': 254},
    {'time': '18:30', 'ct': 340, 'bri': 254},
    {'time': '20:45', 'ct': 400, 'bri': 254},
    {'time': '21:15', 'ct': 440, 'bri': 150},
    {'time': '22:00', 'ct': 480, 'bri': 80},
    {'time': '23:00', 'ct': 500, 'bri': 30},
]

CT_TOLERANCE = 15
CHECK_INTERVAL = 10

prev_light_states = {}


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
    return ct, bri


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


def enforce():
    global prev_light_states

    target_ct, target_bri = get_circadian_now()
    lights = api_get('/lights')
    groups = api_get('/groups')

    for gid, group in groups.items():
        if group.get('type') != 'Room' or not group.get('lights'):
            continue
        if not group.get('state', {}).get('any_on'):
            continue

        needs_correction = False
        for lid in group['lights']:
            light = lights.get(lid)
            if not light or not light.get('state', {}).get('on'):
                continue

            was_off = prev_light_states.get(lid) is False or lid not in prev_light_states
            ct_off = abs((light['state'].get('ct', 0)) - target_ct) > CT_TOLERANCE

            if was_off or ct_off:
                needs_correction = True
                break

        if needs_correction:
            api_put(f'/groups/{gid}/action', {'ct': target_ct, 'bri': target_bri, 'transitiontime': 30})

    prev_light_states = {lid: light['state']['on'] for lid, light in lights.items()}


def main():
    print(f'Circadian Enforcer started — checking every {CHECK_INTERVAL}s')

    while True:
        try:
            if check_circadian_enabled():
                enforce()
                ct, bri = get_circadian_now()
        except Exception as e:
            print(f'Error: {e}')

        time.sleep(CHECK_INTERVAL)


if __name__ == '__main__':
    main()
