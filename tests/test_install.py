"""The installer and the unit file, checked by reading them: the parts that are easy to get wrong
are the ones that only show up on a fresh box in front of a room."""
import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
INSTALL = (SCRIPTS / "install.sh").read_text()
UNINSTALL = (SCRIPTS / "uninstall.sh").read_text()
UNIT = (SCRIPTS / "lab-portal.service").read_text()


def test_the_installer_disables_splunky_finance_rather_than_only_stopping_it():
    """Its service updates itself and reinstalls its own units on boot, so a stop would last until
    the next reboot and the bank app would replace the portal."""
    assert "systemctl disable --now" in INSTALL
    for unit in ("splunky-finance.service", "splunky-finance-egress.timer",
                 "splunky-finance-egress.service"):
        assert unit in INSTALL
    assert "docker compose down" in INSTALL


def test_the_installer_serves_the_port_a_redirect_lands_on():
    """On a splunk.show box 443 is redirected to 8443 in PREROUTING, restored on every boot."""
    assert "8443" in INSTALL
    assert "iptables-save -t nat" in INSTALL
    assert "/etc/iptables/rules.v4" in INSTALL
    assert "--to-ports" in INSTALL


def test_the_installer_refuses_to_take_a_port_from_something_that_is_not_caddy():
    assert "Something other than caddy listens on" in INSTALL


def test_the_installer_never_writes_the_galileo_admin_token():
    """The token is armed from the admin page and held in memory, so an AMI of this box carries no
    Galileo credential."""
    assert "GALILEO_ADMIN_TOKEN" not in INSTALL
    assert "arm it from /admin" in INSTALL


def test_secrets_are_typed_without_being_echoed():
    assert "stty -echo" in INSTALL
    for setting in ("PASSPHRASE", "ADMIN_PASSWORD", "LLM_KEY", "GALILEO_PASSWORD"):
        assert re.search(rf'^\s*ask "[^"]*" {setting} secret$', INSTALL, re.M), setting
    assert "chmod 600" in INSTALL


def test_the_installer_writes_every_value_it_asks_for():
    for placeholder, variable in (("LAB_PASSPHRASE", "PASSPHRASE"), ("ADMIN_PASSWORD", "ADMIN_PASSWORD"),
                                  ("LLM_BASE_URL", "LLM_URL"), ("LLM_MODEL", "LLM_MODEL"),
                                  ("LLM_API_KEY", "LLM_KEY"),
                                  ("GALILEO_USER_PASSWORD", "GALILEO_PASSWORD")):
        assert f'"s|^{placeholder}=.*|{placeholder}=${variable}|"' in INSTALL, placeholder


def test_the_installer_generates_a_session_secret():
    assert "SESSION_SECRET=$(head -c 24 /dev/urandom" in INSTALL


def test_the_roster_is_moved_aside_unless_asked_to_keep_it():
    assert "--keep-data" in INSTALL
    assert "lab.db.$(date" in INSTALL


def test_the_installer_waits_for_the_service_before_declaring_success():
    assert "/healthz" in INSTALL
    assert "journalctl -u lab-portal" in INSTALL


def test_the_unit_runs_as_the_checkout_owner_and_binds_to_loopback():
    assert "User=__USER__" in UNIT
    assert "--host 127.0.0.1" in UNIT
    assert "EnvironmentFile=__ROOT__/.env" in UNIT
    assert "WantedBy=multi-user.target" in UNIT


def test_the_unit_can_write_the_roster_and_nothing_else():
    assert "ProtectSystem=full" in UNIT
    assert "ReadWritePaths=__ROOT__/data" in UNIT
    assert re.search(r"^ReadWritePaths=__ROOT__$", UNIT, re.M) is None


def test_the_unit_trusts_forwarded_headers_only_from_the_local_proxy():
    """client_ip() reads X-Forwarded-For for the rate limiter, which is only safe when uvicorn
    refuses that header from anywhere but Caddy on this box."""
    assert "--forwarded-allow-ips 127.0.0.1" in UNIT


def test_every_placeholder_in_the_unit_is_substituted_by_the_installer():
    placeholders = set(re.findall(r"__[A-Z]+__", UNIT))
    assert placeholders == {"__ROOT__", "__USER__", "__GROUP__", "__PORT__"}
    for placeholder in placeholders:
        assert f"s|{placeholder}|" in INSTALL


def test_uninstall_can_hand_the_box_back():
    assert "systemctl disable --now lab-portal.service" in UNINSTALL
    assert "systemctl enable" in UNINSTALL and "splunky-finance.service" in UNINSTALL
    assert "docker compose up -d" in UNINSTALL
    assert "--wipe" in UNINSTALL


def test_uninstall_keeps_the_roster_unless_told_otherwise():
    assert "roster left in" in UNINSTALL


def test_the_unit_keeps_a_private_tmpfs_directory_across_restarts():
    """Where the armed Galileo key lives: it must outlive a restart, and not a reboot."""
    assert "RuntimeDirectory=lab-portal" in UNIT
    assert "RuntimeDirectoryMode=0700" in UNIT
    assert "RuntimeDirectoryPreserve=yes" in UNIT
