# Splunky Finance lab portal

Registration and the lab guide for the Splunky Finance agent-observability workshop. Participants
open one page, type the workshop passphrase, and are handed their own instance of the bank, their
own Galileo account, and the model endpoint the agent and the judges need.

It is built to run on a box that already has Splunky Finance on it, which it stands down, because
participants get their own instances and this box only needs to be the front door.

## What a participant sees

| Page | |
| --- | --- |
| `/` Overview | the hero with the check-in card, how the session runs, a card per step, house rules |
| `/briefing` Briefing & Setup | the guide's intro, "Before you start" and Steps 1 to 3 |
| `/lab` Workshop lab | Steps 4 to 8: the evaluators and the guardrail |
| `/troubleshooting` | the guide's troubleshooting section |
| `/my-lab` | their own details once checked in |

**Your lab details**, the button at the bottom right of every page, opens their instance URL, bank
logins, Galileo account and the model endpoint. It is filled in from `/api/credentials` behind
their cookie, so no password, key or instance URL is ever in the page source.

The header carries a text `splunk>` wordmark. Drop an official logo at
`app/static/brand/splunk-logo.svg` and the header uses it instead, no restart needed. Set
`EVENT_DATE` and `EVENT_PLACE` in `.env` for the line under the overview headline.

Their Galileo account is created for the address they registered with, which takes three or four
seconds, so the instance URL appears at once and the account arrives while they read Step 1.

## What the instructor does

`/admin`, behind its own password:

| | |
| --- | --- |
| Upload instances | the Splunk Show URLs, as a CSV with a `url` column or one per line |
| Upload fallback accounts | the pre-made `participantN@galileo.ai` list, used only if creation fails |
| Arm account creation | paste a Galileo admin API key; it is exchanged for a token held in memory |
| Watch the roster | who has what, which accounts are created, which fell back, which failed |
| Release or retry | free an instance for somebody else, or try a failed account again |
| Export | the whole roster as CSV |

**Arming is deliberately not persistent.** The admin token lives in one object in memory, is
cleared on disarm, and is lost on restart, so an AMI made from this box carries no Galileo
credential. It has to be armed again after a reboot. While it is disarmed, anyone who registers
waits two minutes and is then handed a fallback account.

## Install

On a fresh boot of the Splunky Finance box:

```sh
git clone https://github.com/roadtrip123/splunky-finance-reg-site.git
cd splunky-finance-reg-site
sudo ./scripts/install.sh --host lab.example.com        # ACME certificate
sudo ./scripts/install.sh --host 3.25.1.2 --mode internal   # self-signed, no DNS needed
```

The installer disables `splunky-finance.service` and its egress timer, stops the containers, builds
the guide, installs `lab-portal.service`, and rewrites `/etc/caddy/Caddyfile` so the portal is the
box's main page. It asks for the passphrase, the admin password and the gateway key without
echoing them, writes `.env` at 0600, and generates a session secret.

`--keep-data` carries a previous roster over. Without it the old database is moved aside.

To hand the box back:

```sh
sudo ./scripts/uninstall.sh --restore-splunky --host lab.example.com
```

## Local development

```sh
uv venv .venv && uv pip install --python .venv/bin/python -e ".[dev]"
cp .env.example .env            # set DRY_RUN=1, a passphrase and an admin password
.venv/bin/python guide/build_guide.py
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8099 --reload
.venv/bin/python -m pytest -q
```

`DRY_RUN=1` keeps the worker offline: nothing is created in Galileo and each participant is shown
their own address as if it had been.

## The guide

`guide/build_guide.py` reads `docs/workshop-lab.md` from the Splunky Finance **branch tip** rather
than from a checkout, because a deployment is pinned to a tag while the guide moves on the branch.
`guide/overlay.py` then applies this event's changes:

* the "Before you start" table, which publishes the two bank passwords, becomes a pointer to the
  details card
* Step 3 and Step 4 point at the card for the endpoint, model and key, so none of the three appear
  in the markdown
* the judge-model paragraph stops naming a model the participant's integration will not list

Every anchor is asserted to match exactly once, so an upstream edit that moves one fails the build
instead of dropping a section. `tests/test_guide.py` runs those assertions against the live branch
tip, which is the test that catches it before a room full of people does.

Screenshots are committed under `app/static/img`. The asset host throttles, and a build that
depends on it is a build that fails on the day.

## Layout

```
app/        FastAPI app: routes, store (SQLite), galileo client, worker, templates, static
guide/      build_guide.py and overlay.py
scripts/    install.sh, uninstall.sh, lab-portal.service
tests/      72 tests, no network
data/       lab.db, gitignored
```

## Afterwards

* Export the roster.
* Rotate the gateway key. It was in a page a hundred people loaded.
* Delete the accounts: `batch_delete_users.py --input-csv <the export>` from the
  galileo-workshop-setup scripts.
