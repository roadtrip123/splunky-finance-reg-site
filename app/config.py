"""Settings, read once at import from the environment and an optional .env beside the repo."""
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("LAB_DATA_DIR") or ROOT / "data")


def load_env_file(path=None):
    """KEY=VALUE pairs into os.environ without overriding anything already set."""
    path = Path(path or ROOT / ".env")
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()


def _int(name, default):
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


class Settings:
    def __init__(self):
        self.passphrase = os.environ.get("LAB_PASSPHRASE", "")
        self.admin_password = os.environ.get("ADMIN_PASSWORD", "")
        self.llm_base_url = os.environ.get("LLM_BASE_URL", "")
        self.llm_model = os.environ.get("LLM_MODEL", "")
        self.llm_api_key = os.environ.get("LLM_API_KEY", "")
        self.galileo_api_url = os.environ.get("GALILEO_API_URL", "").rstrip("/")
        self.galileo_console_url = os.environ.get("GALILEO_CONSOLE_URL", "").rstrip("/")
        self.galileo_agent_control_url = os.environ.get("GALILEO_AGENT_CONTROL_URL", "").rstrip("/")
        self.galileo_password = os.environ.get("GALILEO_USER_PASSWORD", "")
        self.galileo_role = os.environ.get("GALILEO_DEFAULT_ROLE", "user")
        self.bank_account = os.environ.get("BANK_ACCOUNT", "12345678")
        self.bank_password = os.environ.get("BANK_PASSWORD", "AlexDemo1234!")
        self.presenter_password = os.environ.get("PRESENTER_PASSWORD", "PresenterDemo1234!")
        self.account_cap = _int("ACCOUNT_CAP", 130)
        # Optional line under the hero, for example "Thursday 12 November 2026 · Sydney".
        self.event_date = os.environ.get("EVENT_DATE", "")
        self.event_place = os.environ.get("EVENT_PLACE", "")
        self.dry_run = os.environ.get("DRY_RUN", "0") not in ("0", "", "false", "no")
        # Seconds between looks at each participant's instance for the progress board; 0 turns
        # the tracker off.
        self.probe_interval = _int("PROBE_INTERVAL", 30)
        self.stuck_minutes = _int("STUCK_MINUTES", 10)
        self.port = _int("PORT", 8099)
        self.db_path = Path(os.environ.get("LAB_DB") or DATA / "lab.db")
        # Memory-backed, so the armed Galileo key survives restarts and updates but never reaches
        # a disk or a snapshot, and a reboot forgets it. systemd's RuntimeDirectory when the unit
        # has one, otherwise /dev/shm, which is tmpfs on Ubuntu.
        self.runtime_dir = Path(os.environ.get("LAB_RUNTIME_DIR")
                                or os.environ.get("RUNTIME_DIRECTORY")
                                or f"/dev/shm/lab-portal-{os.getuid()}")
        # A generated secret logs everyone out on restart, which is survivable: the cookie only
        # carries a participant token that the database can hand back from their email.
        self.session_secret = os.environ.get("SESSION_SECRET") or secrets.token_urlsafe(32)


settings = Settings()
