"""Wave 5H addenda — AUD-07 (fish env), AUD-24 (bounded mic queue),
AUD-32 (fish log rotation + startup latency).

Verify-first quotes are in docs/status/voice.md; these are the regression
tests for the fixes.

Run:  brain/.venv/bin/python -m pytest brain/voice/tests -q
"""
import asyncio
import sys
import types
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

if "sounddevice" not in sys.modules:
    sys.modules["sounddevice"] = types.ModuleType("sounddevice")

from body.win.audio_in import (QUEUE_MAX_CHUNKS,  # noqa: E402
                               _enqueue_bounded)
from brain.voice.tts import FishSpeechServer  # noqa: E402


# ---- AUD-07: minimal fish env ---------------------------------------------
def test_aud07_fish_env_never_inherits_secrets(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "sk-secret-groq")
    monkeypatch.setenv("HF_TOKEN", "hf_secret_token")
    monkeypatch.setenv("VAST_API_KEY", "vast_secret")
    monkeypatch.setenv("DISCORD_WEBHOOK", "https://discord/secret")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/home/tester")

    env = FishSpeechServer._build_env()
    # process basics kept ...
    assert env["PATH"] == "/usr/bin" and env["HOME"] == "/home/tester"
    # ... hard requirements present ...
    assert env["HF_HUB_OFFLINE"] == "1"
    assert env["no_proxy"] == "127.0.0.1,localhost"
    assert env["PYTHONUNBUFFERED"] == "1"
    # ... and NOT one secret reaches the third-party child
    for secret in ("GROQ_API_KEY", "HF_TOKEN", "VAST_API_KEY",
                   "DISCORD_WEBHOOK"):
        assert secret not in env, f"{secret} leaked into fish env"


def test_aud07_env_allowlist_is_small(monkeypatch):
    """Sanity: a fat os.environ still yields a small, explicit child env."""
    for i in range(50):
        monkeypatch.setenv(f"JUNK_VAR_{i}", "x")
    env = FishSpeechServer._build_env()
    assert not any(k.startswith("JUNK_VAR_") for k in env)
    assert set(env) <= {"PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR",
                        "TEMP", "TMP", "LANG", "LC_ALL", "LD_LIBRARY_PATH",
                        "DYLD_LIBRARY_PATH", "CUDA_VISIBLE_DEVICES",
                        "PYTHONPATH", "PYTHONIOENCODING",
                        "HF_HUB_OFFLINE", "no_proxy", "PYTHONUNBUFFERED"}


# ---- AUD-24: bounded mic queue (drop-oldest) ------------------------------
def test_aud24_queue_is_bounded_and_drops_oldest():
    q = asyncio.Queue(maxsize=QUEUE_MAX_CHUNKS)
    stats = {}
    for i in range(QUEUE_MAX_CHUNKS):
        _enqueue_bounded(q, f"chunk{i}", stats)
    assert q.qsize() == QUEUE_MAX_CHUNKS and "dropped" not in stats

    # overflow: oldest goes, newest in, nothing raises (the old code path
    # raised QueueFull inside call_soon_threadsafe -> loop task death)
    _enqueue_bounded(q, "overflow-1", stats)
    _enqueue_bounded(q, "overflow-2", stats)
    assert q.qsize() == QUEUE_MAX_CHUNKS
    assert stats["dropped"] == 2
    # two overflows dropped the two OLDEST (chunk0, chunk1) — recency wins
    assert q.get_nowait() == "chunk2"
    leftover = []
    while not q.empty():
        leftover.append(q.get_nowait())
    assert leftover[-1] == "overflow-2"      # newest always kept


def test_aud24_drop_is_logged_rate_limited(capsys):
    q = asyncio.Queue(maxsize=3)
    stats = {}
    for i in range(30):
        _enqueue_bounded(q, i, stats)
    out = capsys.readouterr().out
    assert stats["dropped"] == 27
    # 1st drop logged, then only every 500th -> exactly one line for 27
    assert out.count("mic queue full") == 1


def test_aud24_wake_and_ptt_queues_are_bounded():
    """Both audio_in handoffs use the bounded queue (no raw put_nowait left)."""
    src = (_REPO / "body/win/audio_in.py").read_text()
    assert "asyncio.Queue(maxsize=QUEUE_MAX_CHUNKS)" in src
    assert src.count("_enqueue_bounded") >= 3      # def + 2 call sites
    assert ".put_nowait," not in src.replace(           # no raw threaded puts
        "_enqueue_bounded(queue, chunk, stats: dict)", "")


# ---- AUD-32: fish log rotation --------------------------------------------
def test_aud32_small_log_is_not_rotated(tmp_path):
    log = tmp_path / "fish_server.log"
    log.write_bytes(b"tiny")
    assert FishSpeechServer._rotate_log_path(log, max_bytes=1024) is None
    assert log.exists()


def test_aud32_oversized_log_rotates_once(tmp_path):
    log = tmp_path / "fish_server.log"
    log.write_bytes(b"x" * 4096)
    rotated = FishSpeechServer._rotate_log_path(log, max_bytes=1024)
    assert rotated == tmp_path / "fish_server.log.1"
    assert not log.exists()                     # fresh log starts on spawn
    assert rotated.stat().st_size == 4096

    # second rotation: .1 is replaced, never grows a chain
    log.write_bytes(b"y" * 4096)
    FishSpeechServer._rotate_log_path(log, max_bytes=1024)
    assert (tmp_path / "fish_server.log.1").read_bytes() == b"y" * 4096
    assert not (tmp_path / "fish_server.log.2").exists()


def test_aud32_rotation_never_raises(tmp_path):
    assert FishSpeechServer._rotate_log_path(tmp_path / "nope.log") is None
    # a directory where a log should be -> graceful None
    d = tmp_path / "dir.log"
    d.mkdir()
    assert FishSpeechServer._rotate_log_path(d, max_bytes=1) is None


# ---- SEC-9 x pc-control shared helper (depfail) ----------------------------
def test_require_prefers_shared_body_helper(monkeypatch):
    """With the shared helper present, IT produces the pointed SEC-9 error
    for a missing package (their message/manifest wins)."""
    import sys as _sys, types as _t
    calls = []
    fake = _t.ModuleType("body.win.depfail")

    def _req(dist, import_name=None):
        calls.append(dist)
        raise RuntimeError(
            "missing Body dependency '%s' — SEC-9; pip install "
            "--require-hashes -r body/win/requirements.txt" % dist)

    fake.require = _req
    monkeypatch.setitem(_sys.modules, "body.win.depfail", fake)
    from body.win.audio_in import _require_or_die
    with pytest.raises(RuntimeError, match="body/win/requirements.txt"):
        _require_or_die("definitely_not_installed_pkg_xyz_123", "0.0")
    assert calls == ["definitely_not_installed_pkg_xyz_123"]


def test_require_falls_back_when_helper_absent(monkeypatch):
    """depfail not importable -> local check still fails LOUD with BOTH
    manifests named (the audio modules never hard-depend on someone else's
    file landing first)."""
    import sys as _sys
    monkeypatch.setitem(_sys.modules, "body.win.depfail", None)
    from body.win.audio_in import _require_or_die
    with pytest.raises(RuntimeError) as ei:
        _require_or_die("definitely_not_installed_pkg_xyz_123", "0.0")
    assert "SEC-9" in str(ei.value)
    assert "brain/voice/body-audio-requirements.txt" in str(ei.value)
    assert "body/win/requirements.txt" in str(ei.value)


def test_require_present_package_returns_module():
    from body.win.audio_out import _require_or_die
    assert _require_or_die("numpy", "2.2.6").__name__ == "numpy"
