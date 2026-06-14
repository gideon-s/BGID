# Deploying BGID (Hetzner + systemd + nginx)

Same shape as the dreamcrawler boxes: app under `/var/www/bgid`, a Python
`.venv`, run as `www-data` by a systemd unit on `127.0.0.1:8000`, with nginx
proxying the public domain (and WebSocket upgrades) + TLS via certbot.

> **One worker only.** BGID keeps the world (`WorldState`) and WebSocket
> connections in memory, per process. Run a single uvicorn worker. Horizontal
> scaling would require Postgres + Redis pub/sub (the `broadcast_to_room` seam
> is where Redis slots in) — not needed for launch.

## 1. Prerequisites on the box
```bash
apt update && apt install -y python3-venv nginx
# certbot for TLS:
apt install -y certbot python3-certbot-nginx
```

## 2. Get the code + venv
```bash
mkdir -p /var/www/bgid && cd /var/www/bgid
git clone <your-repo-url> .          # or rsync the project here
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 3. Configure
```bash
cp .env.example .env
# Set DEEPSEEK_API_KEY (required). Defaults are fine for the rest.
# DB defaults to sqlite:///./game.db in this directory.
```

## 4. Seed the world (creates game.db)
```bash
.venv/bin/python seed.py        # idempotent; safe to re-run
```

## 5. Permissions
```bash
chown -R www-data:www-data /var/www/bgid
```

## 6. Install + start the service
```bash
cp deploy/bgid-api.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable bgid-api
systemctl start bgid-api
systemctl status bgid-api --no-pager | grep Active
# logs:
journalctl -u bgid-api -f
```

## 7. nginx + domain
```bash
cp deploy/nginx-bgid.conf /etc/nginx/sites-available/bgid
# edit it: replace YOURDOMAIN with your domain
sed -i 's/YOURDOMAIN/phobophilia.com/g' /etc/nginx/sites-available/bgid
ln -s /etc/nginx/sites-available/bgid /etc/nginx/sites-enabled/bgid
nginx -t && systemctl reload nginx
```
Point DNS: an **A record** for the domain → this box's IP. (Your domains use
Bluehost DNS, so set the A record there.) Once it resolves:
```bash
certbot --nginx -d phobophilia.com -d www.phobophilia.com
```
certbot adds the 443 block + http→https redirect. WebSockets then run over
`wss://` automatically (the client picks ws/wss from the page protocol).

Visit `https://phobophilia.com` — the game client loads, you enter a name, and
you're in.

## 8. Updating after a change
The box is a git clone of `origin/main`, owned by `www-data`. Run git as that
user (it owns the tree; running as root trips git's "dubious ownership" guard):
```bash
cd /var/www/bgid
sudo -u www-data git pull --ff-only         # pulls latest origin/main
.venv/bin/pip install -r requirements.txt   # only if deps changed
systemctl restart bgid-api
sleep 2 && systemctl status bgid-api --no-pager | grep Active
```
`.env`, `game.db`, and `.venv` are gitignored, so pulls never touch them.
Static client changes (`static/index.html`) take effect on restart (or
immediately — it's read per request).

## Notes / before-public checklist
- **Auth.** Accounts are username + password (JWT access + refresh, Argon2
  hashing). Set `JWT_SECRET` in `.env` (`python -c "import secrets;print(secrets.token_hex(32))"`).
  The WebSocket is token-authenticated and players may only puppet their own
  characters. The **first account to register becomes admin** (or list names in
  `ADMIN_USERNAMES`); admins gate the world-mutation CRUD. Registration is open
  — add a rate limit on `talk` (DeepSeek cost) before opening widely.
- **LLM cost.** Every `talk` hits the DeepSeek API (real money). Consider a
  per-player cooldown / rate limit before exposing it publicly.
- **Backups.** The whole game state is `game.db`. Back it up if it matters.
- **Schema changes.** Tables are created via `create_all` + `seed.py`. There's
  no migration tool wired up; for additive columns that's fine, for anything
  destructive you'd manage it manually (or add Alembic, already a dependency).
