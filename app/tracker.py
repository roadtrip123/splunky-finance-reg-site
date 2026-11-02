"""Where each participant is in the lab, read from their own Splunky Finance instance.

Nothing on the instance changes. Two existing, read-only endpoints are used:

  GET /ready                    public: is a model configured, the Galileo connection state
  GET /api/demo-admin/status    behind the presenter login every instance shares

A presenter login creates its own session on the instance and leaves the participant's alone:
sessions are keyed by each browser's cookie, so their /demo-admin tab stays signed in. The status
read has no side effects, and its run and events are scoped to the session asking, so the tracker
never sees or touches the link between a participant's banking and presenter tabs. One session per
instance is kept and reused until the instance expires it after an hour.

Steps the instance cannot see, because they happen in the Galileo console (creating and attaching
evaluators) or in another session's runs (the evaluator tests), are ticked by the participant.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from . import store
from .config import settings

TIMEOUT = 8
WORKERS = 8
SELF_STEPS = (1, 4, 5, 6)  # the steps a participant ticks; 1 is also seen automatically
GALILEO_CONNECTED = ("connected", "bound", "registered")


def evaluate(ready, status):
    """(done, under_way, note) from an instance's /ready and presenter status. Either may be None
    when it could not be read; what can be decided from the other still is."""
    done, partial, notes = set(), set(), []
    ready = ready or {}
    galileo = (status or {}).get("galileo") or {}
    provider = ((status or {}).get("provider_status") or {}).get("state", "")
    agent = ((status or {}).get("agent") or {}).get("state", "")
    stages = (status or {}).get("protection_stages") or {}

    # Step 1 and 2: the project exists if the instance found it; connected once a stream is bound.
    if galileo.get("project_id"):
        done.add(1)
    connected = (galileo.get("connection") == "connected"
                 or galileo.get("state") in GALILEO_CONNECTED
                 or ready.get("galileo") in GALILEO_CONNECTED)
    if connected and (galileo.get("log_stream_id") or not status):
        done.add(2)
    elif galileo.get("state") == "failed" or galileo.get("connection") == "failed":
        partial.add(2)
        notes.append("Galileo connection failing")

    # Step 3: a model answered and a trace reached Galileo.
    answered = provider == "connected"
    exported = galileo.get("export") == "exported"
    if answered and exported:
        done.add(3)
    elif answered or exported or ready.get("model") == "configured":
        partial.add(3)
        if provider == "failed":
            notes.append("model calls failing")
    if galileo.get("export") == "failed":
        notes.append("trace export failing")

    # Step 7 and 8: the guardrail decided on a tool call. Registered with Agent Control but not
    # yet deciding is step 7 under way.
    pre = (stages.get("pre") or {}).get("status", "")
    if pre == "verified":
        done.update((7, 8))
    elif agent == "registered" or pre in ("failed", "no_control") or stages:
        partial.add(7)
        if pre == "failed":
            notes.append("guardrail failing")
    if agent == "failed":
        notes.append("Agent Control registration failing")
    return done, partial, "; ".join(notes)


class Tracker:
    def __init__(self):
        self._sessions = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.last_sweep = None
        self.last_error = ""

    def _session(self, box_id):
        with self._lock:
            if box_id not in self._sessions:
                self._sessions[box_id] = requests.Session()
            return self._sessions[box_id]

    def probe(self, box):
        """Look at one instance and record what it shows. Returns (done, partial, note)."""
        base = box["url"].rstrip("/")
        session = self._session(box["id"])
        ready = status = None
        notes = []
        try:
            response = session.get(f"{base}/ready", timeout=TIMEOUT)
            if response.headers.get("content-type", "").startswith("application/json"):
                ready = response.json()
        except requests.RequestException as error:
            store.record_probe(box["id"], False, f"unreachable ({type(error).__name__})")
            return set(), set(), "unreachable"
        except ValueError:
            pass

        try:
            response = session.get(f"{base}/api/demo-admin/status", timeout=TIMEOUT)
            if response.status_code == 401:
                login = session.post(f"{base}/api/demo-admin/login", timeout=TIMEOUT,
                                     json={"password": settings.presenter_password},
                                     headers={"Origin": base})
                if login.status_code == 401:
                    notes.append("presenter login refused")
                elif login.status_code == 403:
                    notes.append("instance rejected this site's origin")
                elif login.ok:
                    response = session.get(f"{base}/api/demo-admin/status", timeout=TIMEOUT)
            if response.ok:
                status = response.json()
        except (requests.RequestException, ValueError) as error:
            notes.append(f"status unreadable ({type(error).__name__})")

        done, partial, note = evaluate(ready, status)
        if note:
            notes.append(note)
        if status is None and not notes:
            notes.append("status unreadable")
        for step in done:
            store.mark_step(box["participant_id"], step, "auto")
        store.record_probe(box["id"], True, "; ".join(notes), partial - done)
        return done, partial, "; ".join(notes)

    def sweep(self):
        boxes = [b for b in store.assigned_boxes() if store.clean_url(b["url"])]
        if boxes:
            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                list(pool.map(self._safe_probe, boxes))
        self.last_sweep = time.time()
        return len(boxes)

    def _safe_probe(self, box):
        try:
            return self.probe(box)
        except Exception as error:  # one odd instance must not stop the sweep
            self.last_error = f"{type(error).__name__}: {error}"[:200]
            return None

    def start(self):
        if settings.probe_interval <= 0 or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="lab-tracker", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.sweep()
            except Exception as error:
                self.last_error = f"{type(error).__name__}: {error}"[:200]
            self._stop.wait(settings.probe_interval)


tracker = Tracker()
