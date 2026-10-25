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
sudo -u moshspot mkdir -p /opt/moshspot/sim/runs
# plus the MoshSpot worker repo, e.g. /opt/moshspot/worker
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
Give the worker its own `moshspot-worker.service` with `EnvironmentFile=/etc/moshspot/bridge.env` and the worker's start command.

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
Put the QR code on the Devpost page or a slide. The token is in the URL **fragment**, which browsers never send to the server. The page saves it for the tab and removes it from the address bar.

The token gives **full control** (streaming frames, dispatching). There's no separate read-only role. **Rotate it after judging:** edit `/etc/moshspot/bridge.env`, then `sudo systemctl restart moshspot-bridge moshspot-worker`.

## 10. Replay-as-live content
Record runs locally (`python3 bridge.py --record`, then **Record run** in the page) and copy them up:
```bash
aws s3 sync runs/demo-s7-20261025220245 s3://<bucket>/runs/demo-s7-20261025220245     # from your laptop
aws s3 sync s3://<bucket>/runs/demo-s7-20261025220245 /opt/moshspot/sim/runs/demo-s7-20261025220245   # on the instance
```
Point the worker's replay mode at `runs/<run>/CAM-n/%06d.jpg`, at the `fps` in that run's `gt.json`.

## OpenCV fallback
If the COOL listing for your instance doesn't ship OpenCV 5 yet, stay on Graviton and install the `opencv-python` 5.x aarch64 wheel in a virtualenv for the worker. Benchmark both if you're entering the COOL award: the award is for *using* COOL, so keep the COOL build wherever its version is enough.

## Costs and teardown
You pay EC2 on-demand for the instance, plus the COOL hourly software fee after its trial (see the listing), plus the Elastic IP and EBS storage. When judging ends:
```bash
# stop or terminate the instance, then release the Elastic IP and delete leftover EBS volumes/snapshots;
# cancel the COOL subscription in AWS Marketplace → Manage subscriptions if you won't use it again
```

## Not covered here
- The worker's own build and config (it lives in its own repo).
- CloudWatch logs and alarms.
- Autoscaling, and multiple simultaneous live sims (that needs per-session camera IDs in the bridge).
