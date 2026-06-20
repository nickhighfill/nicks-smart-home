# Nick's Smart Home Dashboard

## What This Is
Single-page Hue light dashboard served from a Raspberry Pi (steve.local:8080).

## Architecture
- `index.html` — the full dashboard (all-in-one HTML/CSS/JS)
- `server.py` — Flask backend for Spotify/Chromecast integration
- Hosted on Raspberry Pi 3 Model A+ (hostname: steve, user: steve)
- Auto-pulls from GitHub every minute via cron

## Hue Bridge
- IP: 192.168.0.2 (HTTP)
- API Key: v-I9tLBE0xEPKGNWMMqihE1YpzArq9eviFkA7SOZ
- 7 lights across 5 rooms

## Deployment
- Push to GitHub -> Pi auto-pulls within 60 seconds
- Dashboard served via systemd service (python3 http.server on port 8080)
- Access from phone: http://steve.local:8080

## Pi Details
- SSH: ssh steve@steve.local (key-based auth from Mac)
- Password: admin
- OS: Raspberry Pi OS 32-bit
