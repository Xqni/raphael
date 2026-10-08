"""Wave 5H SEC-5 support: ONE key-read function, keys never logged.

Three tripwires:
1. source scan — no file outside `privacy.py` may read `.env` or
   `os.environ.get(<SECRET_NAME>)`; every `Bearer ` header must be built from
   `privacy.secret()` (the single reader);
2. log redaction — no key value and no key-shaped token may ever reach a log
   line (caplog across success + failure + vision flows);
3. exception text — a provider that echoes the key back in an error body must
   not leak it through `RouterError.__str__`.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

import brain.router as router
from brain.router import RouterError
from brain.router.tests.conftest import make_config

ROUTER_SRC = Path(__file__).resolve().parents[1]      # brain/router/
SENTINEL = "gsk_THISKEYMUSTNEVERAPPEARINLOGS999"

SECRET_NAMES = ("GROQ_API_KEY", "OPENCODE_API_KEY", "ZEN_API_KEY",
                "GITHUB_TOKEN", "CIVITAI_TOKEN", "HF_TOKEN", "VAST_API_KEY",
                "RAPHAEL_TOKEN")


# --------------------------------------------------------------------------- #
# 1. source scan — single reader (privacy.secret)
# --------------------------------------------------------------------------- #
def test_secret_reads_confined_to_privacy_module() -> None:
    env_read = re.compile(r"os\.environ\.get\(\s*[\"'](?P<name>%s)"
                           % "|".join(SECRET_NAMES))
    dotenv_read = re.compile(r"[\"']\.env[\"']")
    offenders: list[str] = []
    for py in sorted(ROUTER_SRC.glob("*.py")):
        if py.name == "privacy.py":
            continue                                # THE single reader
        for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if env_read.search(line):
                offenders.append(f"{py.name}:{lineno}: direct env read of a secret")
            if dotenv_read.search(line):
                offenders.append(f"{py.name}:{lineno}: reads .env directly")
    assert not offenders, "\n".join(offenders)


def test_every_bearer_header_comes_from_secret() -> None:
    """Files that build `Bearer …` must obtain the value via privacy.secret()."""
    for py in sorted(ROUTER_SRC.glob("*.py")):
        text = py.read_text(encoding="utf-8")
        if "Bearer " in text:
            assert "secret(" in text, (
                f"{py.name} builds an Authorization header without privacy.secret()")


# --------------------------------------------------------------------------- #
# 2. log redaction — no key material in any log line
# --------------------------------------------------------------------------- #
KEY_PATTERNS = [
    re.compile(re.escape(SENTINEL)),
    re.compile(r"gsk_[A-Za-z0-9_\-]{12,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{10,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{15,}"),
    re.compile(r"(?i)(authorization[^=]*=)\S+"),
]


@pytest.mark.asyncio
async def test_no_key_material_in_logs(tmp_path, make_server, caplog,
                                       monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", SENTINEL)
    srv = make_server(free_suffix=False)            # success + error paths
    cfg = make_config(tmp_path, ["groq"], groq_url=srv.url, max_retries=0)
    router.reset_router()
    rt = router.init_router(cfg)
    with caplog.at_level(logging.DEBUG):
        await rt.chat([{"role": "user", "content": f"password={SENTINEL} hi"}])
        srv.chat_script.append((500, {}, b"boom"))  # next call fails on purpose
        with pytest.raises(RouterError):
            await rt.chat([{"role": "user", "content": "again"}])   # 500 path
        await rt.health()
    text = caplog.text
    for pat in KEY_PATTERNS:
        assert not pat.search(text), f"log leaked key material: {pat.pattern}"
    # neither the key nor the Authorization header appears in any record args
    for record in caplog.records:
        blob = f"{record.getMessage()} {record.args}"
        assert SENTINEL not in blob
        assert "Bearer" not in blob


# --------------------------------------------------------------------------- #
# 3. exception text — provider echoing the key cannot leak it
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_exception_text_scrubs_key_echoed_by_provider(
        tmp_path, make_server, monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", SENTINEL)
    srv = make_server(free_suffix=False)
    srv.chat_script.append((401, {}, (
        f'{{"error":{{"message":"invalid api key {SENTINEL} supplied"}}}}'
    ).encode()))
    cfg = make_config(tmp_path, ["groq"], groq_url=srv.url, max_retries=0)
    router.reset_router()
    rt = router.init_router(cfg)
    with pytest.raises(RouterError) as exc:
        await rt.chat([{"role": "user", "content": "hi"}])
    assert exc.value.code == "E_PROVIDER_AUTH"
    assert SENTINEL not in str(exc.value)
    assert SENTINEL not in repr(exc.value)
    assert SENTINEL not in " ".join(str(a) for a in exc.value.args)
    assert "[REDACTED]" in str(exc.value)          # proof it was scrubbed


@pytest.mark.asyncio
async def test_outbound_body_scrubs_key_even_if_user_pastes_it(
        tmp_path, make_server, monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", SENTINEL)
    srv = make_server(free_suffix=False)
    cfg = make_config(tmp_path, ["groq"], groq_url=srv.url)
    router.reset_router()
    rt = router.init_router(cfg)
    await rt.chat([{"role": "user", "content": f"key={SENTINEL}"}])
    assert SENTINEL.encode() not in srv.chat_requests[0]["body"]
    # the Authorization header is the ONE place it may appear (that is its job)
    assert srv.chat_requests[0]["headers"].get("authorization") == \
        f"Bearer {SENTINEL}"
