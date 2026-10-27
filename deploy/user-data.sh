#!/bin/bash
# MoshSpot instance bootstrap (EC2 user-data). Rendered by aws-deploy.sh; contains NO secrets:
# the bridge token is fetched from SSM Parameter Store with the instance role and written root-only.
set -euo pipefail
exec > >(tee -a /var/log/moshspot-bootstrap.log) 2>&1
echo "== moshspot bootstrap $(date -u +%FT%TZ)"

REGION="__REGION__"
BUCKET="__BUCKET__"
PARAM="__PARAM__"
DOMAIN="__DOMAIN__"
REPO="https://github.com/Gofer-AI/gofer-moshspot"
REPO_SHA="__REPO_SHA__"
RUN="__RUN__"
MODE="__MODE__"            # live | replay
WORKER_FPS="__WORKER_FPS__"
EXPIRES_SYSTEMD="__EXPIRES_SYSTEMD__"   # e.g. 2026-11-15 22:00:00 UTC
APP=/opt/moshspot/sim

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends caddy git python3-venv unattended-upgrades
snap install aws-cli --classic >/dev/null 2>&1 || true
AWS=$(command -v aws || echo /snap/bin/aws)

# Nothing listens for SSH (no key pair, port closed in the security group); stop the daemon too.
systemctl disable --now ssh.socket ssh.service 2>/dev/null || true
systemctl enable --now unattended-upgrades

# ---- code, pinned to the exact commit that was reviewed
id moshspot >/dev/null 2>&1 || useradd --system --create-home --home-dir /opt/moshspot --shell /usr/sbin/nologin moshspot
if [ ! -d "$APP/.git" ]; then
  sudo -u moshspot git clone --quiet "$REPO" "$APP"
fi
sudo -u moshspot git -C "$APP" fetch --quiet origin "$REPO_SHA" || true
sudo -u moshspot git -C "$APP" -c advice.detachedHead=false checkout --quiet "$REPO_SHA"
sudo -u moshspot mkdir -p "$APP/models" "$APP/runs/live"

# ---- models + calibration (and replay frames) from the private deploy bucket
"$AWS" s3 cp --quiet --recursive "s3://$BUCKET/models/" "$APP/models/" --region "$REGION"
"$AWS" s3 cp --quiet --recursive "s3://$BUCKET/runs/$RUN/" "$APP/runs/$RUN/" --region "$REGION"
chown -R moshspot:moshspot "$APP/models" "$APP/runs"

# ---- Python: COOL's interpreter if the AMI has it, else a venv with the stock OpenCV 5 wheel. Hash-pinned.
PY=""
for cand in /opt/cool/venvs/python_3.12/bin/python /opt/cool/venvs/*/bin/python; do
  # the worker needs OpenCV 5 (cv.dnn ENGINE_NEW); a COOL build older than that falls through to the stock wheel
  if [ -x "$cand" ] && "$cand" -c "import sys, cv2; sys.exit(int(cv2.__version__.split('.')[0]) < 5)" 2>/dev/null; then PY="$cand"; break; fi
done
if [ -n "$PY" ]; then
  "$PY" -m pip install --quiet --require-hashes --no-deps -r "$APP/deploy/requirements.lock.txt"
else
  echo "!! COOL Python not found; using stock opencv-contrib-python 5 in /opt/moshspot/venv"
  python3 -m venv /opt/moshspot/venv
  /opt/moshspot/venv/bin/pip install --quiet --require-hashes --no-deps -r "$APP/deploy/requirements-local.lock.txt"
  PY=/opt/moshspot/venv/bin/python
fi
"$PY" -c "import cv2, numpy, scipy; print('cv2', cv2.__version__, 'numpy', numpy.__version__, 'scipy', scipy.__version__)"

# ---- token: SSM SecureString -> root-only env file (systemd reads it before dropping to the service user)
install -d -m 700 /etc/moshspot
umask 077
TOKEN=$("$AWS" ssm get-parameter --name "$PARAM" --with-decryption --query Parameter.Value --output text --region "$REGION")
printf 'MOSHSPOT_TOKEN=%s\n' "$TOKEN" > /etc/moshspot/bridge.env
unset TOKEN
umask 022

# ---- services
REPLAY=""
[ "$MODE" = "replay" ] && REPLAY="--replay $APP/runs/$RUN"
cat > /etc/systemd/system/moshspot-bridge.service <<EOF
[Unit]
Description=MoshSpot sim bridge
After=network-online.target
Wants=network-online.target

[Service]
User=moshspot
EnvironmentFile=/etc/moshspot/bridge.env
ExecStart=/usr/bin/python3 $APP/bridge.py --host 127.0.0.1 --port 8780
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
ReadWritePaths=$APP/runs

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/moshspot-worker.service <<EOF
[Unit]
Description=MoshSpot worker (OpenCV 5 / COOL)
After=moshspot-bridge.service
Wants=moshspot-bridge.service

[Service]
User=moshspot
EnvironmentFile=/etc/moshspot/bridge.env
# cap decoded image size (4K) so a hostile JPEG can't balloon memory
Environment=OPENCV_IO_MAX_IMAGE_PIXELS=8294400
WorkingDirectory=$APP
ExecStart=$PY -m moshspot.worker --bridge http://127.0.0.1:8780 --calibration $APP/runs/$RUN/gt.json --fps $WORKER_FPS --out $APP/runs/live $REPLAY
Restart=on-failure
RestartSec=5
Nice=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
ReadWritePaths=$APP/runs

[Install]
WantedBy=multi-user.target
EOF

# ---- HTTPS (Let's Encrypt, automatic). The bridge itself sets CSP, X-Frame-Options, nosniff, no-referrer.
cat > /etc/caddy/Caddyfile <<EOF
$DOMAIN {
	request_body {
		max_size 40MB
	}
	reverse_proxy 127.0.0.1:8780 {
		flush_interval -1
	}
	header {
		Strict-Transport-Security "max-age=31536000"
		Permissions-Policy "camera=(), microphone=(), geolocation=()"
		-Server
	}
}
EOF

# ---- backup expiry (the primary is an EventBridge Scheduler job that terminates the instance):
# shut down at the expiry time; the instance is launched with shutdown behaviour = terminate.
cat > /etc/systemd/system/moshspot-expire.service <<'EOF'
[Unit]
Description=MoshSpot demo expiry
[Service]
Type=oneshot
ExecStart=/usr/sbin/shutdown -h now "MoshSpot demo expired"
EOF
cat > /etc/systemd/system/moshspot-expire.timer <<EOF
[Unit]
Description=MoshSpot demo expiry
[Timer]
OnCalendar=$EXPIRES_SYSTEMD
Persistent=true
[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now moshspot-bridge moshspot-worker moshspot-expire.timer
systemctl reload caddy || systemctl restart caddy
echo "== moshspot bootstrap done $(date -u +%FT%TZ)"
