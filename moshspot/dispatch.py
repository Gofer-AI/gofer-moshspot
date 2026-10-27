"""Dispatch EMT teams through the bridge API, wait for acknowledgement, and escalate when nobody accepts.

Team choice uses emt_router.py (Dijkstra over the venue floor, slowed by the crowd MoshSpot is tracking), so
MoshSpot and the sim agree on who is really nearest. Every call is logged to the incident's trace.
"""

import json
import logging
import time
import urllib.request

from emt_router import EmtRouter

log = logging.getLogger(__name__)
ACK_TIMEOUT = 45.0  # s for a team to accept before the next team is sent


class Dispatcher:
    def __init__(self, bridge_url, venue, token=None, ack_timeout=ACK_TIMEOUT):
        self.bridge_url = bridge_url.rstrip("/")
        self.token = token
        self.router = EmtRouter.from_venue_json(venue)
        self.ack_timeout = ack_timeout
        self.jobs = {}       # incident id -> {"incident", "team", "tried", "sent_at", "status"}
        self.busy = set()
        self._last_event = 0

    def dispatch(self, incident, people=(), lying=()):
        job = self.jobs.setdefault(incident.id, {"incident": incident, "tried": [], "status": None})
        ranking = self.router.rank(incident.X, incident.Y, people, list(lying) + [(incident.X, incident.Y)],
                                   busy=self.busy | set(job["tried"]))
        choice = next((r for r in ranking if r.available and r.eta_s < float("inf")), None)
        incident.log(time.time(), "rank_teams", ranking=[{"team": r.team, "eta_s": round(r.eta_s, 1),
                                                          "straight_m": round(r.straight_m, 1), "free": r.available}
                                                         for r in ranking])
        if choice is None:
            incident.log(time.time(), "escalate", reason="no free team can reach the patient; control room alerted")
            return None
        self._post({"action": "dispatch", "team": choice.team, "X": incident.X, "Y": incident.Y,
                    "incident_id": incident.id})
        job.update(team=choice.team, sent_at=time.monotonic(), status="dispatched")
        job["tried"].append(choice.team)
        self.busy.add(choice.team)
        incident.log(time.time(), "dispatch_team", team=choice.team, eta_s=round(choice.eta_s, 1))
        return choice.team

    def poll(self, people=(), lying=()):
        """Read team events from the bridge; re-dispatch any job nobody accepted in time."""
        events = self._get(f"/emt?after={self._last_event}")
        for event in events.get("events", []):
            self._last_event = max(self._last_event, event.get("seq", 0))
            job = self.jobs.get(event.get("incident_id") or "")
            if job is None:
                job = next((j for j in self.jobs.values() if j.get("team") == event.get("team")
                            and j["status"] not in ("resolved", "false_alarm", "cancelled")), None)
            status = event.get("status")
            if job and status:
                job["status"] = status
                job["incident"].log(time.time(), "team_status", team=event.get("team"), status=status,
                                    **{k: event[k] for k in ("eta_s", "response_s") if k in event})
            if status in ("resolved", "false_alarm", "cancelled", "available"):
                self.busy.discard(event.get("team"))
        now = time.monotonic()
        for job in self.jobs.values():
            if job["status"] == "dispatched" and now - job["sent_at"] > self.ack_timeout:
                job["incident"].log(time.time(), "escalate", team=job["team"],
                                    reason=f"no acknowledgement in {self.ack_timeout:.0f} s; sending the next team")
                self._post({"action": "cancel", "team": job["team"], "incident_id": job["incident"].id})
                self.busy.discard(job["team"])
                self.dispatch(job["incident"], people, lying)

    def publish(self, incidents, keep=40, steps=24):
        """Share the newest incidents and their traces with the bridge, for the page's incidents panel."""
        snapshot = [{"id": i.id, "state": i.state, "priority": i.priority, "X": round(i.X, 2), "Y": round(i.Y, 2),
                     "cameras": sorted(i.cameras), "cluster": i.cluster, "trace": i.trace[-steps:]}
                    for i in incidents[-keep:]]
        self._post({"incidents": snapshot}, "/incidents")

    def _post(self, body, path="/dispatch"):
        request = urllib.request.Request(f"{self.bridge_url}{path}", data=json.dumps(body).encode(),
                                         headers=self._headers({"Content-Type": "application/json"}), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.loads(response.read() or b"{}")
        except OSError as error:
            log.warning("dispatch call failed: %s", error)
            return {}

    def _get(self, path):
        request = urllib.request.Request(f"{self.bridge_url}{path}", headers=self._headers({}))
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.loads(response.read() or b"{}")
        except OSError as error:
            log.warning("bridge poll failed: %s", error)
            return {}

    def _headers(self, headers):
        return {**headers, "Authorization": f"Bearer {self.token}"} if self.token else headers
