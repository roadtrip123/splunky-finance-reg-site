#!/usr/bin/env python3
"""Why the progress board shows what it shows for one participant.

Does what the tracker does every PROBE_INTERVAL seconds, once, and prints its working: the
participant's row, the last look at their instance, the steps recorded, then a fresh read of the
instance and the steps that read would mark. Read-only on the instance; prints no secrets.

    .venv/bin/python scripts/check_progress.py someone@example.com
    .venv/bin/python scripts/check_progress.py --url https://other-instance.splunk.show
    .venv/bin/python scripts/check_progress.py someone@example.com --url https://...

--url reads a different instance, for when someone worked on a box other than the one the site
assigned them. Nothing is recorded from a --url read.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from app import store  # noqa: E402
from app.config import settings  # noqa: E402
from app.tracker import evaluate  # noqa: E402


def participant(email):
    person = store.by_email(email)
    if not person:
        print(f"{email} has not checked in on this site (check the spelling on the roster)")
        return None
    print(f"checked in:        {person['name']} | {person['state']} | galileo {person['galileo_state']}")
    print(f"assigned instance: {store.clean_url(person['box_url']) or 'NONE'}")
    db = store.connect()
    try:
        probe = db.execute("SELECT * FROM probes WHERE box_id=?", (person["box_id"],)).fetchone()
    finally:
        db.close()
    if probe:
        print(f"last look:         {int(time.time() - probe['checked_at'])}s ago | reachable "
              f"{bool(probe['reachable'])} | note '{probe['note']}' | under way '{probe['partial']}'")
    else:
        print("last look:         never")
    print(f"steps recorded:    {[(s['step'], s['source']) for s in store.steps_for(person['id'])]}")
    print(f"probe interval:    {settings.probe_interval}s"
          + ("  (0 means the tracker is off)" if settings.probe_interval <= 0 else ""))
    return person


def read_instance(url):
    url = url.rstrip("/")
    print(f"\nreading {url}")
    session = requests.Session()
    try:
        ready = session.get(f"{url}/ready", timeout=10)
    except requests.RequestException as error:
        print(f"  unreachable: {type(error).__name__}")
        return
    print(f"  /ready:             HTTP {ready.status_code} {ready.text[:200]}")
    login = session.post(f"{url}/api/demo-admin/login", timeout=10,
                         json={"password": settings.presenter_password}, headers={"Origin": url})
    print(f"  presenter login:    HTTP {login.status_code}"
          + ("" if login.ok else f" {login.text[:160]}"))
    status = session.get(f"{url}/api/demo-admin/status", timeout=10)
    print(f"  presenter status:   HTTP {status.status_code}")
    data = status.json() if status.ok else None
    if data:
        galileo = data.get("galileo") or {}
        print(f"  galileo:            { {k: galileo.get(k) for k in ('state', 'connection', 'export')} }"
              f" project set {bool(galileo.get('project_id'))},"
              f" stream set {bool(galileo.get('log_stream_id'))}")
        if galileo.get("last_error"):
            print(f"  galileo last error: {str(galileo['last_error'])[:160]}")
        print(f"  model provider:     {(data.get('provider_status') or {}).get('state')}")
        print(f"  agent control:      {(data.get('agent') or {}).get('state')}")
        stages = {k: v.get("status") for k, v in (data.get("protection_stages") or {}).items()}
        print(f"  guardrail:          {data.get('protection_status')} {stages}")
    try:
        ready_json = ready.json()
    except ValueError:
        ready_json = None
    done, partial, note = evaluate(ready_json, data)
    print(f"\n  would mark done:    {sorted(done) or 'nothing'}")
    print(f"  under way:          {sorted(partial - done) or 'nothing'}")
    if note:
        print(f"  note:               {note}")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("email", nargs="?")
    parser.add_argument("--url", help="read this instance instead of the assigned one")
    args = parser.parse_args()
    if not args.email and not args.url:
        parser.error("give an email, a --url, or both")
    person = participant(args.email) if args.email else None
    url = args.url or (store.clean_url(person["box_url"]) if person else "")
    if url:
        read_instance(url)
    elif person:
        print("\nno instance assigned, so nothing to read")


if __name__ == "__main__":
    main()
