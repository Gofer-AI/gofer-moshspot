# Deploying MoshSpot on AWS Graviton with COOL

One Graviton EC2 instance runs everything:
- **The MoshSpot worker** uses COOL (Cloud-Optimized OpenCV Library: OpenCV tuned for Graviton, from AWS Marketplace) for detection, pose and tracking. COOL accelerates the worker, not this repo.
- **The sim bridge** (`bridge.py`, standard library only) serves the simulator and its camera streams, and carries dispatches to the simulated EMT teams.
- **Caddy** provides HTTPS with an automatic Let's Encrypt certificate. It's the only thing exposed to the internet.

```
judge's browser ──HTTPS 443──► Caddy ──► bridge.py 127.0.0.1:8780 ◄── MJPEG ?token / POST /dispatch ── MoshSpot worker (COOL)
   (renders the sim, streams frames up;                                                              same instance, localhost
    EMT teams walk on dispatch)
```

**Demo modes.** Run both:
- **Replay-as-live (always on, no browser needed):** the worker loops a recorded run (`runs/<run>/CAM-n/%06d.jpg`). Judges always see a working system.
- **Live sim (on demand):** a judge opens `https://<domain>/#token=…`. Their browser draws the concert and streams the four cameras to the bridge. The worker detects collapses and dispatches, and the EMTs walk to the patient in the judge's browser.
  > ⚠️ Run **one live sim at a time**. Camera IDs are shared, so two open tabs mix their frames.

---

## Quick deploy with the AWS CLI (one command, auto-expires)

`deploy/aws-deploy.sh` does steps 2–9 below for you: least-privilege IAM, a private bucket, the token in SSM, the instance, HTTPS, systemd services, and an expiry. `deploy/aws-teardown.sh` removes everything.

```bash
aws login                                    # sign in (AWS CLI v2)
bash tools/export_models.sh                  # once: writes models/*.onnx
git push                                     # the instance clones the exact pushed commit

DOMAIN=moshspot.<your-domain> \
AMI_ID=<COOL Graviton AMI id for your region> \
RUN=<a recorded run in runs/, e.g. demo-s7-20261025220245> \
HOSTED_ZONE_ID=<Route 53 zone, optional: creates the A record> \
deploy/aws-deploy.sh
```

**DNS on Vercel (goferai.space):** leave `HOSTED_ZONE_ID` unset. The script ends by printing the record to add: type `A`, name `moshspot`, value = the instance IP, TTL 60. Add it under Vercel → Domains → goferai.space → DNS Records, or run `vercel dns add goferai.space moshspot A <IP>`. **Delete it when the demo ends:** the AWS expiry can't reach Vercel, and a record left pointing at a released IP can be taken over.

| Default | Why |
|---|---|
| `INSTANCE_TYPE=c8g.large` (2 vCPU / 4 GB, Graviton4) | the smallest size that runs the worker; if `journalctl -u moshspot-worker` shows it falling behind, redeploy with `c8g.xlarge` |
| `WORKER_FPS=1` per camera | tiled detection is the expensive step; 1 fps still catches a fall (onset is judged over 2 s, immobility over 8 s) |
| `MODE=live` | judges' browsers drive the sim. `MODE=replay` loops `RUN` with no browser |
| `DAYS=20` | EventBridge Scheduler **terminates the instance** (and deletes the Route 53 record, so the name can't dangle at a recycled IP) when time is up. An on-instance timer is the backup. Bucket objects expire 2 days later |

**Rough cost for 20 days**, on-demand in us-east-1: about $40. That's c8g.large ≈ $38, the public IPv4 address ≈ $2.40, and 20 GB of gp3 ≈ $1. **Add COOL's hourly software fee** after its free trial (see your listing). Set `BUDGET_USD=60 BUDGET_EMAIL=you@…` to get an alert.

**What the script locks down:**
- **Access:** no SSH (no key pair; port 22 closed; use `aws ssm start-session`), and only 443/80 are open.
- **Instance:** IMDSv2 required with hop limit 1, and an encrypted root disk.
- **Instance role:** it can read only its own bucket and its own SSM parameter.
- **Token:** generated locally, stored as an SSM SecureString, and written root-only on the box. It never appears in user-data, command lines, or logs.
- **Python dependencies:** installed with `--require-hashes` from `deploy/requirements*.lock.txt`.
- **Code:** pinned to the commit you deployed.
- **Services:** systemd sandboxing (`ProtectSystem=strict`, `NoNewPrivileges`, `PrivateDevices`, …).
- **HTTPS:** Caddy with HSTS. The bridge also sends a CSP that only allows the page's own scripts (by hash) and the integrity-checked three.js.

**The judge link** is written to `deploy/judge-link-<name>.txt` (gitignored, mode 600). **Never post it publicly** (not on the public Devpost page, the README, or the video): anyone with it can dispatch and stream. Give it to judges through a private channel, such as Devpost's judges-only fields or the organisers' email.

The rest of this file is the same setup step by step, for when you want to do it by hand.

---

## 1. Subscribe to COOL
1. In AWS Marketplace, search for **COOL / Cloud Optimized OpenCV Library** (publisher: OpenCV) and pick the listing that matches the Graviton generation you'll launch. There are separate Graviton4 and Graviton5 listings.
2. Check that listing's **OpenCV version, Python version, trial length and hourly software fee**. MoshSpot needs **OpenCV 5** (for `cv.dnn` ENGINE_NEW). If your listing ships 4.x, see [OpenCV fallback](#opencv-fallback).
3. Subscribe.

## 2. Launch the instance
From the listing, choose **Continue to Launch → Launch through EC2**.

| Setting | Value |
|---|---|
| Instance type | `c8g.xlarge` (Graviton4, 4 vCPU / 8 GB), or the size the listing supports. Start here for 4 cameras at 5 fps, then watch CPU and resize |
| Storage | 30 GB gp3 (more if you keep many recorded runs: a 3-minute 720p run is about 600 MB) |
| IAM role | one with `AmazonSSMManagedInstanceCore`, so you can use **Session Manager instead of SSH** |
| Security group | inbound **443** and **80** from anywhere (80 only serves the HTTPS redirect and Let's Encrypt). **No port 22, no 8780** |
| Public IP | allocate an **Elastic IP** and associate it |

DNS: create an `A` record such as `moshspot.<your-domain>` pointing to the Elastic IP (in Route 53 or wherever the domain lives).

## 3. Check COOL's OpenCV
Connect with **EC2 → Connect → Session Manager**, then:
```bash
python3 -c "import cv2; print(cv2.__version__)"
python3 - <<'EOF'
import cv2
info = cv2.getBuildInformation()
for key in ("General configuration", "FFMPEG", "dnn", "KleidiCV", "NEON", "Python 3"):
    print([l.strip() for l in info.splitlines() if key in l][:2])
EOF
```
You need:
- **5.x** for the version;
- **FFMPEG: YES**, so the worker can open MJPEG and RTSP URLs;
- **dnn** among the built modules.

If COOL installs its own Python, use that interpreter everywhere below; the listing's usage instructions say which one. The bridge works on any Python 3.9+.

## 4. Install the code
```bash
sudo useradd --system --create-home --home-dir /opt/moshspot --shell /usr/sbin/nologin moshspot
sudo -u moshspot git clone https://github.com/Gofer-AI/gofer-moshspot /opt/moshspot/sim
sudo -u moshspot mkdir -p /opt/moshspot/sim/runs /opt/moshspot/sim/models
```

**The worker lives in the same repo (`moshspot/`).** Install it into COOL's Python, so it runs on COOL's `cv2` build. The path below comes from the Graviton4 listing's usage notes; use whatever path your listing gives.

Install the worker without its pip OpenCV wheel, then install scipy:

```bash
sudo /opt/cool/venvs/python_3.12/bin/python -m pip install --no-deps -e /opt/moshspot/sim
sudo /opt/cool/venvs/python_3.12/bin/python -m pip install "scipy>=1.18"
```

Check that it picks up COOL's OpenCV 5:

```bash
/opt/cool/venvs/python_3.12/bin/python -c "import cv2, moshspot.worker; print(cv2.__version__)"
```

**Models.** The ONNX models are portable, so export them on a laptop (`bash tools/export_models.sh`) and copy them up. From the laptop:

```bash
aws s3 cp --recursive models/ s3://<bucket>/models/ --exclude "*.pt"
```

On the instance:

```bash
sudo -u moshspot aws s3 cp --recursive s3://<bucket>/models/ /opt/moshspot/sim/models/
```

## 5. Create the token
```bash
sudo install -d -m 700 /etc/moshspot
echo "MOSHSPOT_TOKEN=$(openssl rand -hex 24)" | sudo tee /etc/moshspot/bridge.env >/dev/null
sudo chmod 600 /etc/moshspot/bridge.env
sudo cat /etc/moshspot/bridge.env    # copy it; you'll need it for the worker and the judge link
```
The token goes only in this file, which systemd reads as root. It never appears on a command line, where `ps` would show it.

## 6. Run the bridge as a service
`/etc/systemd/system/moshspot-bridge.service`:
```ini
[Unit]
Description=MoshSpot sim bridge
After=network-online.target
Wants=network-online.target

[Service]
User=moshspot
EnvironmentFile=/etc/moshspot/bridge.env
# Loopback only: Caddy on this same box is the public face. Add --record only if the cloud copy should save runs.
ExecStart=/usr/bin/python3 /opt/moshspot/sim/bridge.py --host 127.0.0.1 --port 8780
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/opt/moshspot/sim/runs

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now moshspot-bridge
systemctl status moshspot-bridge --no-pager     # "auth=on  record=off"
```

The worker uses the same env file, and talks to the bridge on localhost, so the token never crosses the network:
```python
TOKEN = os.environ["MOSHSPOT_TOKEN"]
cap = cv.VideoCapture(f"http://127.0.0.1:8780/mjpeg/CAM-1?token={TOKEN}")
requests.post("http://127.0.0.1:8780/dispatch", json={...}, headers={"Authorization": f"Bearer {TOKEN}"})
```
The worker gets its own service, `/etc/systemd/system/moshspot-worker.service`. It needs a calibration file: any recorded run's `gt.json` at the same resolution works, because the cameras are fixed.

```ini
[Unit]
Description=MoshSpot worker (OpenCV 5 / COOL)
After=moshspot-bridge.service
Wants=moshspot-bridge.service

[Service]
User=moshspot
EnvironmentFile=/etc/moshspot/bridge.env
WorkingDirectory=/opt/moshspot/sim
# Live sim: watch the bridge's MJPEG streams and dispatch the sim's EMT teams.
# For the always-on demo with no browser, add: --replay /opt/moshspot/sim/runs/<run>
ExecStart=/opt/cool/venvs/python_3.12/bin/python -m moshspot.worker --bridge http://127.0.0.1:8780 --calibration /opt/moshspot/sim/runs/<run>/gt.json --out /opt/moshspot/sim/runs/live
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/opt/moshspot/sim/runs

[Install]
WantedBy=multi-user.target
```

Enable it, then follow its log:

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now moshspot-worker
journalctl -u moshspot-worker -f     # "watching CAM-1, CAM-2, CAM-3, CAM-4", then help rings, ALERT and dispatch lines
```

Alerts go to `runs/live/alerts.jsonl`, and the agent's step-by-step traces to `runs/live/traces.jsonl`.

## 7. HTTPS with Caddy
Install Caddy from its official apt repository (follow the Debian/Ubuntu steps at caddyserver.com/docs/install). Then set `/etc/caddy/Caddyfile`:
```caddyfile
moshspot.<your-domain> {
	request_body {
		max_size 40MB
	}
	reverse_proxy 127.0.0.1:8780 {
		flush_interval -1   # pass MJPEG frames through immediately
	}
	header {
		Strict-Transport-Security "max-age=31536000"
		-Server
	}
}
```
```bash
sudo systemctl reload caddy
```
Caddy gets and renews the certificate on its own, and redirects port 80 to 443. Leave Caddy's access log **off**, which is the default: MJPEG URLs carry `?token=` in the query string.

### Option B: Application Load Balancer instead of Caddy
- Run the bridge with `--host 0.0.0.0` (it refuses to start without `MOSHSPOT_TOKEN`).
- The instance security group allows **8780 only from the ALB's security group**.
- Target group: HTTP on 8780, health check `GET /status`.
- Listener: HTTPS on 443 with an ACM certificate, plus a redirect from 80.
- Raise the ALB **idle timeout** (for example to 3600 s), because a paused sim sends no frames and the default of 60 s would cut viewers off.
- Optionally attach AWS WAF with a rate-based rule.

## 8. Smoke test
```bash
D=https://moshspot.<your-domain>; T=<token>
curl -s $D/status                                                    # {"ok": true, "auth_required": true, "record": false, ...}
curl -s -o /dev/null -w "%{http_code}\n" $D/emt                      # 401
curl -s -H "Authorization: Bearer $T" $D/emt                         # {"teams": {}, "events": [], "last": 0}
```
Then open `$D/#token=$T` in a browser. The header should show **bridge: connected**. On the instance:
```bash
T=$T python3 -c "import cv2,os; c=cv2.VideoCapture('http://127.0.0.1:8780/mjpeg/CAM-1?token='+os.environ['T']); print(c.read()[0])"   # True
```

## 9. Judge flow (QR code)
```bash
sudo apt-get install -y qrencode
qrencode -o judge-qr.png "https://moshspot.<your-domain>/#token=<token>"
```
Share the QR code or link **privately with judges** (a judges-only submission field or the organisers' email), never on a public page. The token is in the URL **fragment**, which browsers never send to the server. The page saves it for the tab and removes it from the address bar.

The token gives **full control** (streaming frames, dispatching). There's no separate read-only role. **Rotate it after judging:** edit `/etc/moshspot/bridge.env`, then `sudo systemctl restart moshspot-bridge moshspot-worker`.

## 10. Replay-as-live content
Record runs locally (`python3 bridge.py --record`, then **Record run** in the page) and copy them up:
```bash
aws s3 sync runs/demo-s7-20261025220245 s3://<bucket>/runs/demo-s7-20261025220245     # from your laptop
aws s3 sync s3://<bucket>/runs/demo-s7-20261025220245 /opt/moshspot/sim/runs/demo-s7-20261025220245   # on the instance
```
Point the worker at the run with `--replay runs/<run>`. It loops all four cameras at real speed, timed by the `fps` in that run's `gt.json`.

## 10b. COOL benchmark (Best Use of COOL award)

Run the same benchmark on each configuration and commit the JSON files it writes to `eval/results/`:

| Configuration | Interpreter |
|---|---|
| c8g + COOL | COOL's Python |
| c8g + stock OpenCV | a plain venv with `pip install opencv-python==5.0.0.93` |
| c7i (x86) + stock OpenCV | the laptop or an x86 instance |

On c8g with COOL, for example:

```bash
cd /opt/moshspot/sim && /opt/cool/venvs/python_3.12/bin/python tools/benchmark_cool.py runs/<run> --frames 60 \
    --price-per-hour <c8g.xlarge on-demand + COOL fee> --label c8g-cool
```

Each file records:

- per-stage milliseconds: decode, imgproc, tiled detection, full perception;
- cameras at 5 fps per instance;
- $ per camera-hour;
- the KleidiCV/HAL lines from `cv2.getBuildInformation()`, which prove which build ran.

## OpenCV fallback
If the COOL listing for your instance doesn't ship OpenCV 5 yet, stay on Graviton and install the `opencv-python` 5.x aarch64 wheel in a virtualenv for the worker. Benchmark both if you're entering the COOL award: the award is for *using* COOL, so keep the COOL build wherever its version is enough.

## Costs and teardown
You pay EC2 on-demand for the instance, plus the COOL hourly software fee after its trial (see the listing), plus the Elastic IP and EBS storage. When judging ends:
```bash
# stop or terminate the instance, then release the Elastic IP and delete leftover EBS volumes/snapshots;
# cancel the COOL subscription in AWS Marketplace → Manage subscriptions if you won't use it again
```

## Not covered here
- CloudWatch logs and alarms (the services log to journald; the CloudWatch agent can ship them).
- Autoscaling, and multiple simultaneous live sims (that needs per-session camera IDs in the bridge).
