"""ARCH-6 — `raphael doctor` tests: actionable rows, value-blind output,
exit semantics. Uses tmp env/log files; stack probes tolerated down."""
import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "raphael_cli_under_test", _ROOT / "scripts" / "raphael_cli.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

SECRET = "sk-must-never-appear-in-doctor-output-123456"


def test_env_check_is_value_blind(tmp_path):
    env = tmp_path / ".env"
    env.write_text("GROQ_API_KEY=%s\nGITHUB_TOKEN=\nOTHER=plain\n" % SECRET)
    status, name, detail, fix = cli._check_env_file(env)
    assert name == ".env"
    assert "GROQ_API_KEY" in detail          # key NAMES are fine
    assert "GITHUB_TOKEN" in detail and "empty" in detail
    assert SECRET not in detail              # values NEVER leak
    assert SECRET not in str(fix)
    assert "values never shown" in detail


def test_env_check_mode_warn_and_fix(tmp_path):
    env = tmp_path / ".env"
    env.write_text("GROQ_API_KEY=x\n")
    env.chmod(0o644)
    status, _n, _d, fix = cli._check_env_file(env)
    assert status == "WARN" and "chmod 600" in fix


def test_token_check_modes(tmp_path):
    class Ctx:
        token_path = str(tmp_path / "token")
    (tmp_path / "token").write_text("fake-token")
    (tmp_path / "token").chmod(0o600)
    status, _n, detail, fix = cli._check_token(Ctx())
    assert status == "PASS" and "present" in detail and fix is None
    assert "fake-token" not in detail        # value-blind
    (tmp_path / "token").chmod(0o644)
    status, _n, _d, fix = cli._check_token(Ctx())
    assert status == "WARN" and "chmod 600" in fix


def test_supervisor_log_structured_audit(tmp_path):
    good = tmp_path / "supervisor.log"
    good.write_text(
        "[2026-10-07 12:00:00] INFO started\n"
        "[2026-10-07 12:00:05] WARN flaky\n"
        "[2026-10-07 12:00:06] ERROR boom\n")
    status, _n, detail, _f = cli._check_supervisor_log(good)
    assert status == "PASS"
    assert "3/3 tail lines timestamped" in detail and "1 ERROR" in detail
    bad = tmp_path / "unstructured.log"
    bad.write_text("just some text\nno timestamps\n")
    status, _n, detail, fix = cli._check_supervisor_log(bad)
    assert status == "WARN" and "NOT structured" in detail
    assert "[YYYY-MM-DD" in fix


def test_disk_check_reports_free_space():
    status, _n, detail, _f = cli._check_disk()
    assert status in ("PASS", "WARN", "FAIL", "SKIP")
    if status != "SKIP":
        assert "free" in detail


def test_doctor_end_to_end_value_blind(tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_text("GROQ_API_KEY=%s\n" % SECRET)
    env.chmod(0o600)
    log = tmp_path / "supervisor.log"
    log.write_text("[2026-10-07 12:00:00] INFO ok\n")
    args = cli.build_parser().parse_args(
        ["doctor", "--env-file", str(env), "--log-file", str(log)])
    cfg, _ = cli.sup.load_config()
    ctx = cli.Ctx(cfg)
    rc = cli.cmd_doctor(ctx, args)
    out = capsys.readouterr().out
    assert SECRET not in out, "doctor leaked a value"
    assert "DOCTOR RESULT: PASS=" in out
    assert "raphael doctor — instance=" in out
    assert rc in (0, 1)                      # 1 only if a real FAIL appeared
    # every row is [STATUS] name — detail
    for line in out.splitlines():
        if line.startswith("["):
            assert line[1:5].rstrip("]") in ("PASS", "WARN", "FAIL", "SKIP") \
                or line[1:5] in ("PASS", "WARN", "FAIL", "SKIP")
