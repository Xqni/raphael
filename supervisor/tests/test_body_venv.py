"""Body pinned-venv resolution (Wave-2 task 6: system Python 3.10 EOL)."""
import sys
from pathlib import Path

from supervisor import main as sup


def test_body_script_uses_configured_pinned_venv(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    fake_py = tmp_path / "body-venv" / "Scripts" / "python.exe"
    fake_py.parent.mkdir(parents=True)
    fake_py.write_text("")                 # existence is all we check
    cfg, _ = sup.load_config()
    cfg["paths"]["body_venv"] = str(fake_py.parent.parent)
    exe, argv, script_path, why = sup.body_script(cfg)
    assert why == ""
    assert exe == str(fake_py)             # pinned venv wins over sys python
    assert argv[1].endswith("main.py")


def test_body_script_falls_back_to_system_python(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    cfg, _ = sup.load_config()
    cfg["paths"]["body_venv"] = str(tmp_path / "does-not-exist")
    exe, argv, script_path, why = sup.body_script(cfg)
    assert why == ""
    assert exe == sys.executable           # historical default, unchanged


def test_explicit_python_path_in_body_cmd_respected(tmp_path, monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    explicit = tmp_path / "pin" / "python.exe"
    explicit.parent.mkdir(parents=True)
    explicit.write_text("")
    cfg, _ = sup.load_config()
    cfg["paths"]["body_cmd"] = "%s body/win/main.py" % explicit
    exe, argv, script_path, why = sup.body_script(cfg)
    assert exe == str(explicit)            # deliberate pin is never overridden


def test_lookup_order_config_first(monkeypatch, tmp_path):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    configured = tmp_path / "a" / "python.exe"
    configured.parent.mkdir(parents=True)
    configured.write_text("")
    cfg, _ = sup.load_config()
    cfg["paths"]["body_venv"] = str(configured)
    assert sup.body_venv_python(cfg) == configured


def test_body_venv_python_none_when_everything_missing(monkeypatch,
                                                       tmp_path):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    cfg, _ = sup.load_config()
    cfg["paths"]["body_venv"] = str(tmp_path / "nope")
    # repo .venv-body does not exist on this machine -> None
    result = sup.body_venv_python(cfg)
    assert result is None or Path(result).is_file()
