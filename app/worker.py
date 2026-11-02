"""The background account creator.

The admin token lives here and nowhere else: in memory, in one object, cleared on disarm and lost
on restart. That is deliberate, so an AMI made from this box carries no Galileo credential.

Three states matter to a participant standing in the room:
  armed      accounts are created for the address they registered with
  disarmed   nothing is created, and after POOL_AFTER seconds they are handed a pre-made account
             from the pool instead of being left staring at a spinner
  dry run    nothing leaves the box; their own address is echoed back as if it had been created
"""
import threading
import time

from . import galileo, runtime, store
from .config import settings

POOL_AFTER = 120  # disarmed: seconds before a pre-made account beats an explanation
ARMED_POOL_AFTER = 300  # armed: accounts are made one at a time, so a long queue needs a backstop
MAX_ATTEMPTS = 3


class Creator:
    def __init__(self):
        self._lock = threading.Lock()
        self._token = ""
        self._identity = {}
        self._armed_at = None
        self._thread = None
        self._stop = threading.Event()
        self.last_error = ""
        self.last_created_at = None
        self.created_here = 0

    # ------------------------------------------------------------ arming

    def arm(self, api_key):
        """Exchange the key for a bearer token and keep the token only. The key itself is not
        stored, so it cannot be read back out of the process by anything short of a debugger."""
        token, identity = galileo.exchange_api_key(settings.galileo_api_url, api_key)
        with self._lock:
            self._token = token
            self._identity = identity
            self._armed_at = time.time()
            self.last_error = ""
        return identity

    def disarm(self):
        with self._lock:
            self._token = ""
            self._identity = {}
            self._armed_at = None

    @property
    def armed(self):
        with self._lock:
            return bool(self._token)

    def status(self):
        with self._lock:
            return {
                "armed": bool(self._token),
                "dry_run": settings.dry_run,
                "identity": dict(self._identity),
                "armed_at": self._armed_at,
                "last_error": self.last_error,
                "last_created_at": self.last_created_at,
                "created_here": self.created_here,
            }

    # ------------------------------------------------------------ loop

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="galileo-creator", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self):
        """Idle once a second, but carry straight on while there is a queue: a room of a hundred
        registering at once drains in the time the calls take, not that plus a second each."""
        busy = False
        while busy or not self._stop.wait(1.0):
            if self._stop.is_set():
                return
            try:
                busy = bool(self.tick())
            except Exception as error:  # a worker that dies takes the whole event with it
                self.last_error = f"{type(error).__name__}: {error}"[:300]
                busy = False

    def tick(self):
        """One unit of work. Called by the loop, and directly by the tests."""
        if settings.dry_run:
            return self._tick_dry_run()
        if self.armed:
            return self._tick_create()
        return self._tick_fallback()

    def _tick_dry_run(self):
        row = store.next_queued()
        if not row:
            return None
        store.set_galileo(row["id"], "ready", email=row["email"],
                          password=runtime.get("galileo_password"))
        self.last_created_at = time.time()
        return row["email"]

    def _tick_create(self):
        if store.created_count() > settings.account_cap:
            return self._tick_fallback()
        # Nobody waits more than five minutes, however long the queue is: a pre-made account in
        # their hand beats a spinner while the fiftieth account is still being made.
        starving = store.waiting_since(time.time() - ARMED_POOL_AFTER)
        if starving and store.issue_pool_account(starving["id"]):
            return starving["email"]
        row = store.next_queued()
        if not row:
            return None
        first, _, last = (row["name"] or "").partition(" ")
        with self._lock:
            token = self._token
        password = runtime.get("galileo_password")
        try:
            # Already a member of this organisation: they keep their own login, and nothing is
            # created, so no invitation goes out and no duplicate is attempted.
            existing = galileo.find_user(settings.galileo_api_url, token, row["email"])
            if existing:
                note = ""
                if existing.get("role") == "read_only":
                    note = ("existing account is read-only, so it cannot create a project; "
                            "raise its role in Galileo")
                store.set_galileo(row["id"], "existing", email=row["email"], error=note,
                                  password="")
                return row["email"]
            galileo.create_user(
                settings.galileo_api_url, token, row["email"], password,
                role=settings.galileo_role, first_name=first.strip() or "Workshop",
                last_name=last.strip() or "Participant")
        except galileo.Duplicate:
            # Taken, but not in this organisation: an account elsewhere on the platform, which
            # would need an invitation to reach this console. A workshop account, at once.
            note = "has a Galileo account outside this organisation; given a workshop account"
            if not store.issue_pool_account(row["id"], note=note):
                store.set_galileo(row["id"], "failed", error=note.split(";")[0] +
                                  "; no workshop account left to give")
            return None
        except galileo.GalileoError as error:
            self.last_error = str(error)[:300]
            if row["attempts"] >= MAX_ATTEMPTS:
                if not store.issue_pool_account(row["id"]):
                    store.set_galileo(row["id"], "failed", error=str(error))
            else:
                store.requeue(row["id"], str(error))
            return None
        store.set_galileo(row["id"], "ready", email=row["email"], password=password)
        self.last_created_at = time.time()
        self.created_here += 1
        return row["email"]

    def _tick_fallback(self):
        """Disarmed, or over the cap. Nobody waits forever: anyone queued longer than POOL_AFTER
        gets a pre-made account, and the admin page shows the row in amber so you know why."""
        cutoff = time.time() - POOL_AFTER
        for row in store.roster():
            if row["galileo_state"] in ("queued", "creating") and row["created_at"] < cutoff:
                if not store.issue_pool_account(row["id"]):
                    store.set_galileo(row["id"], "failed",
                                      error="account creation is not armed and the pool is empty")
                return row["email"]
        return None


creator = Creator()
