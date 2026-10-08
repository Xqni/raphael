"""Router configuration loading (INTERFACES §(c)).

Load order, later wins:
  1. `config.yaml` (base, integrator-owned)
  2. `config.d/*.yaml` fragments — sorted by filename, deep-merged
     (mappings merge recursively; lists/scalars replace)
  3. the active profile overlay: `profiles.<profile>` from the merged tree
Profile source: `RAPHAEL_PROFILE` env (wins) → top-level `profile:` → `cloud_temp`.

Router-specific knobs live under the top-level `router:` key — this lane's
fragment is `config.d/router.yaml` (AGENT_RULES §3: config changes go in
`config.d/<lane>.yaml`, never in the base file).

Secrets are NEVER read here. Providers read `GROQ_API_KEY` / `OPENCODE_API_KEY`
at call time, presence-checked value-blind (INTERFACES §a).

Env shortcuts (tests / lane isolation):
  RAPHAEL_ROUTER_MOCK=1 → chain = ["mock"] (deterministic mock provider).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.yaml"

try:  # PyYAML ships in brain/.venv; the fallback keeps bare-python imports alive
    import yaml as _yaml
except Exception:  # noqa: BLE001 — optional dependency
    _yaml = None  # type: ignore[assignment]


# --------------------------------------------------------------------------- #
# Fallback loader (only used when PyYAML is unavailable)
# --------------------------------------------------------------------------- #
def _simple_yaml_load(path: Path) -> dict[str, Any]:
    """Minimal YAML loader for the flat/nested structure used in config.yaml."""
    result: dict[str, Any] = {}
    current_stack: list[tuple[int, dict[str, Any]]] = [(0, result)]
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("#") or not line.strip():
                    continue
                indent = len(line) - len(line.lstrip(" "))
                content = line.strip()
                if content.startswith("-") or ":" not in content:
                    continue
                key, value = content.split(":", 1)
                key, value = key.strip(), value.strip()
                while current_stack and current_stack[-1][0] >= indent and len(current_stack) > 1:
                    current_stack.pop()
                parent = current_stack[-1][1]
                if value == "":
                    new_dict: dict[str, Any] = {}
                    parent[key] = new_dict
                    current_stack.append((indent + 2, new_dict))
                else:
                    parent[key] = _scalar(value)
    except FileNotFoundError:
        return result
    return result


def _scalar(value: str) -> Any:
    if value.startswith("[") and value.endswith("]"):
        items = value[1:-1].strip()
        return [] if not items else [i.strip().strip("'\"") for i in items.split(",")]
    if value.startswith("{") and value.endswith("}"):
        out: dict[str, Any] = {}
        inner = value[1:-1].strip()
        if not inner:
            return out
        for part in inner.split(","):
            if ":" not in part:
                continue
            k, v = part.split(":", 1)
            out[k.strip().strip("'\"")] = _scalar(v.strip())
        return out
    low = value.lower()
    if low in ("true", "false"):
        return low == "true"
    if value.isdigit():
        return int(value)
    try:
        return float(value) if "." in value else int(value)
    except ValueError:
        return value.strip("'\"")


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        if _yaml is not None:
            data = _yaml.safe_load(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        return _simple_yaml_load(path)
    except Exception:  # noqa: BLE001 — a broken fragment must not kill boot
        return {}


def deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """INTERFACES §(c): mappings merge recursively; lists/scalars replace."""
    out: dict[str, Any] = dict(base)
    for key, val in (over or {}).items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], val)
        else:
            out[key] = val
    return out


# --------------------------------------------------------------------------- #
# Authority guard (AUD-02, AUDIT-2026-10-07 P0)
#
# The router loader used to deep-merge config.d fragments with NO authority
# strip — a fragment could pivot `providers.groq_base_url` (key exfil), flip
# `allow_paid_runtime`, or inject `profiles:` (pivot the overlay). The policy
# is brain-core's Core-Guard (brain/config.py:129 AUTHORITY_KEYS + wholesale
# `profiles` strip, qa APPROVED 2026-10-07); this module now uses that loader
# as the SINGLE authoritative merger when importable, and otherwise applies
# the EXACT same policy locally (fail CLOSED: base values win, loudly logged).
# --------------------------------------------------------------------------- #
AUTHORITY_KEYS: tuple[str, ...] = ("safety", "privacy", "providers")

_local_violations: list[dict[str, Any]] = []


def _brain_cfg():
    """brain-core's config module = the authoritative merger (light import:
    os/threading/Path only; `brain` is a PEP 420 namespace package)."""
    try:
        from brain import config as brain_cfg  # noqa: WPS433 (lazy on purpose)
        return brain_cfg
    except Exception:  # noqa: BLE001 — standalone/venv runs fall back below
        return None


def authority_violations() -> list[dict[str, Any]]:
    """Violations recorded during the last loads (delegates to brain-core's
    Core-Guard list when that loader is active)."""
    mod = _brain_cfg()
    if mod is not None:
        try:
            return list(mod.authority_violations())
        except Exception:  # noqa: BLE001
            pass
    return list(_local_violations)


def _strip_fragment(frag: dict[str, Any], name: str) -> dict[str, Any]:
    """EXACT brain/config.py `_merge_fragment` policy (keep for the fallback
    path): safety/privacy/providers/profiles are integrator-only."""
    if not frag:
        return frag
    stripped = [k for k in AUTHORITY_KEYS if k in frag]
    if "profiles" in frag:
        stripped.append("profiles")
    if stripped:
        _local_violations.append({"file": name, "keys": stripped})
        print(f"[router/config] AUTHORITY VIOLATION in config.d/{name}: "
              f"stripped {stripped} — safety/privacy/providers/profiles are "
              "integrator-only (AGENT_RULES §3/§8); base values kept",
              flush=True)
        frag = {k: v for k, v in frag.items() if k not in stripped}
    return frag


def _merged_tree(cfg_path: Path) -> dict[str, Any]:
    """base → config.d (authority-stripped) → profile overlay (INTERFACES §c).

    Uses brain-core's loader when importable so there is ONE authority policy
    in the repo; the local path below is byte-for-byte the same policy."""
    mod = _brain_cfg()
    if mod is not None:
        try:
            return dict(mod.load_config(cfg_path, force=True))
        except Exception:  # noqa: BLE001 — fall through to the local loader
            pass
    data = _load_yaml(cfg_path)
    config_d = cfg_path.parent / "config.d"
    if config_d.is_dir():
        for frag in sorted(config_d.glob("*.yaml")):
            data = deep_merge(data, _strip_fragment(_load_yaml(frag), frag.name))
    profile = (os.environ.get("RAPHAEL_PROFILE")
               or str(data.get("profile") or "cloud_temp"))
    overlay = (_get(data, "profiles") or {}).get(profile)
    if isinstance(overlay, dict):
        data = deep_merge(data, overlay)
    data["profile"] = profile
    return data


# --------------------------------------------------------------------------- #
# Defaults (code-side; config can override every one of them)
# --------------------------------------------------------------------------- #
from .roles import DEFAULT_DENY_HINTS, DEFAULT_PURPOSE_ROLES, DEFAULT_ROLE_HINTS  # noqa: E402
from .spend import DEFAULT_PRICE_PER_MTOK  # noqa: E402

DEFAULT_CHAIN = ["go", "zen_free", "groq"]  # USER 2026-10-07: opencode models own LLM chain; groq = STT-only tail

DEFAULT_RPM: dict[str, int] = {
    "groq": 30,
    "zen_free": 12,
    "go": 10,
    "ollama": 60,
    "mock": 100000,
}

DEFAULT_TPM: dict[str, int] = {
    "groq": 60000,
    "zen_free": 12000,
    "go": 30000,
    "ollama": 200000,
    "mock": 10_000_000,
}


# --------------------------------------------------------------------------- #
# Settings dataclasses (defaults keep older constructions source-compatible)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ProviderEndpoints:
    zen_base_url: str = "https://opencode.ai/zen/v1"
    go_base_url: str = "https://opencode.ai/zen/go/v1"


@dataclass(frozen=True)
class RouterSettings:
    chain: list[str]
    allow_go_runtime: bool
    allow_paid_runtime: bool
    allow_free_models_for_personal_data: bool
    zen_base_url: str
    go_base_url: str
    discovery_interval_s: int
    max_calls_per_minute: int
    benchmark_ranking_path: str
    # --- Wave 2 additions (defaults => older call sites keep working) ---
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_key_env: str = "GROQ_API_KEY"
    zen_key_env: str = "OPENCODE_API_KEY"
    role_hints: dict[str, list[str]] = field(
        default_factory=lambda: {k: list(v) for k, v in DEFAULT_ROLE_HINTS.items()}
    )
    deny_hints: list[str] = field(default_factory=lambda: list(DEFAULT_DENY_HINTS))
    zen_free_hints: list[str] = field(default_factory=lambda: ["free"])
    purpose_roles: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_PURPOSE_ROLES)
    )
    rpm: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_RPM))
    tpm: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_TPM))
    max_retries: int = 2
    backoff_base_s: float = 0.4
    backoff_cap_s: float = 8.0
    request_timeout_s: float = 45.0
    stream_timeout_s: float = 90.0
    discovery_timeout_s: float = 8.0
    usage_log_path: str = ""          # "" -> <repo_root>/brain/router/usage.jsonl
    block_chat_on_blocklist: bool = True
    require_foreground: bool = True   # AUD-05: unknown foreground → REFUSE
                                      # cloud chat/vision (integrator escape:
                                      # config.d/router.yaml can flip false)
    vision_max_bytes: int = 4_000_000  # defensive cap; caller pre-downscales (§7)
    local_stt_enabled: bool = True     # profile local: voice lane registers the seam
    # --- vision-only paid slot (USER APPROVAL 2026-10-06, docs/PAID_USAGE.md) ---
    # gates ONE Go-tier vision model for vision() purpose ONLY; chat/tools/STT
    # keep using allow_go_runtime/allow_paid_runtime (both stay false).
    allow_vision_paid: bool = False
    vision_paid_daily_cap_usd: float = 1.00
    vision_paid_total_cap_usd: float = 10.00   # SEC-8 all-time ceiling
    vision_paid_unknown_call_floor_usd: float = 0.005  # conservative charge
    vision_paid_price_per_mtok: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_PRICE_PER_MTOK)
    )

    def rpm_for(self, provider: str) -> int:
        return int(self.rpm.get(provider, self.max_calls_per_minute))

    def tpm_for(self, provider: str) -> int:
        return int(self.tpm.get(provider, 12000))


@dataclass(frozen=True)
class LocalModelSettings:
    candidates: list[str] = field(default_factory=list)
    text: str = "auto"
    vision: str = "auto"
    keep_alive: str = "5m"
    vision_keep_alive: str = "0"
    max_concurrency: int = 1
    ollama_url: str = "http://127.0.0.1:11434"
    enabled: bool = False              # profile cloud_temp -> False


@dataclass(frozen=True)
class PrivacySettings:
    blocklist_apps: tuple[str, ...] = ()
    redact: tuple[str, ...] = ("api_key", "token", "password", "card", "email", "phone")
    debug_capture: bool = False


@dataclass(frozen=True)
class VisionSettings:
    provider: str = "cloud"            # cloud (cloud_temp) | local (profile local)
    max_px: int = 1280
    quality: int = 70
    max_bytes: int = 4_000_000


@dataclass(frozen=True)
class VoiceSettings:
    stt_engine: str = "groq"           # groq (cloud_temp) | local (profile local)
    stt_model: str = "small"           # faster-whisper size (local seam)
    stt_language: str = ""
    wake_word: str = ""                # whisper prompt-bias hint (STT only)


@dataclass(frozen=True)
class RouterConfig:
    providers: RouterSettings
    local_model: LocalModelSettings
    repo_root: Path
    profile: str = "cloud_temp"
    privacy: PrivacySettings = field(default_factory=PrivacySettings)
    vision: VisionSettings = field(default_factory=VisionSettings)
    voice: VoiceSettings = field(default_factory=VoiceSettings)

    @property
    def usage_log_path(self) -> Path:
        custom = (self.providers.usage_log_path or "").strip()
        if custom:
            p = Path(custom)
            return p if p.is_absolute() else self.repo_root / p
        return self.repo_root / "brain" / "router" / "usage.jsonl"


def _get(data: dict[str, Any], key: str) -> dict[str, Any]:
    val = data.get(key)
    return dict(val) if isinstance(val, dict) else {}


def _as_str_list(val: Any, fallback: list[str]) -> list[str]:
    if isinstance(val, list):
        return [str(x) for x in val]
    if isinstance(val, str) and val:
        return [v.strip() for v in val.split(",") if v.strip()]
    return list(fallback)


def load_config(path: Path | None = None) -> RouterConfig:
    """Load the effective config (base → config.d → profile overlay → env)."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    data = _merged_tree(cfg_path)   # authority-guarded merge (AUD-02)
    profile = os.environ.get("RAPHAEL_PROFILE") or str(data.get("profile") or "cloud_temp")

    providers_data = _get(data, "providers")
    local_data = _get(data, "local_model")
    privacy_data = _get(data, "privacy")
    vision_data = _get(data, "vision")
    voice_data = _get(data, "voice")
    router_data = _get(data, "router")

    chain = _as_str_list(providers_data.get("chain"), DEFAULT_CHAIN)
    if os.environ.get("RAPHAEL_ROUTER_MOCK") == "1":
        chain = ["mock"]  # deterministic mock for other lanes' tests

    rpm = dict(DEFAULT_RPM)
    rpm.update({str(k): int(v) for k, v in _get(router_data, "rpm").items()})
    tpm = dict(DEFAULT_TPM)
    tpm.update({str(k): int(v) for k, v in _get(router_data, "tpm").items()})

    role_hints = {k: list(v) for k, v in DEFAULT_ROLE_HINTS.items()}
    for role, hints in _get(router_data, "role_hints").items():
        role_hints[str(role)] = _as_str_list(hints, [])
    deny_hints = _as_str_list(router_data.get("deny_hints"),
                              list(DEFAULT_DENY_HINTS))
    zen_free_hints = _as_str_list(router_data.get("zen_free_hints"), ["free"])
    purpose_roles = dict(DEFAULT_PURPOSE_ROLES)
    purpose_roles.update({str(k): str(v) for k, v in _get(router_data, "purpose_roles").items()})

    providers = RouterSettings(
        chain=chain,
        allow_go_runtime=bool(providers_data.get("allow_go_runtime", False)),
        allow_paid_runtime=bool(providers_data.get("allow_paid_runtime", False)),
        allow_free_models_for_personal_data=bool(
            providers_data.get("allow_free_models_for_personal_data", False)
        ),
        zen_base_url=str(providers_data.get("zen_base_url", "https://opencode.ai/zen/v1")),
        go_base_url=str(providers_data.get("go_base_url", "https://opencode.ai/zen/go/v1")),
        groq_base_url=str(
            providers_data.get("groq_base_url", "https://api.groq.com/openai/v1")
        ),
        groq_key_env=str(providers_data.get("groq_key_env", "GROQ_API_KEY")),
        zen_key_env=str(providers_data.get("zen_key_env", "OPENCODE_API_KEY")),
        discovery_interval_s=int(providers_data.get("discovery_interval_s", 3600)),
        max_calls_per_minute=int(providers_data.get("max_calls_per_minute", 12)),
        benchmark_ranking_path=str(
            providers_data.get("benchmark_ranking_path", "brain/router/benchmark_ranking.json")
        ),
        role_hints=role_hints,
        deny_hints=deny_hints,
        zen_free_hints=zen_free_hints,
        purpose_roles=purpose_roles,
        rpm=rpm,
        tpm=tpm,
        max_retries=int(router_data.get("max_retries", 2)),
        backoff_base_s=float(router_data.get("backoff_base_s", 0.4)),
        backoff_cap_s=float(router_data.get("backoff_cap_s", 8.0)),
        request_timeout_s=float(router_data.get("request_timeout_s", 45.0)),
        stream_timeout_s=float(router_data.get("stream_timeout_s", 90.0)),
        discovery_timeout_s=float(router_data.get("discovery_timeout_s", 8.0)),
        usage_log_path=str(router_data.get("usage_log_path", "")),
        block_chat_on_blocklist=bool(router_data.get("block_chat_on_blocklist", True)),
        require_foreground=bool(router_data.get("require_foreground", True)),
        vision_max_bytes=int(router_data.get("vision_max_bytes", 4_000_000)),
        allow_vision_paid=bool(providers_data.get("allow_vision_paid", False)),
        vision_paid_daily_cap_usd=float(
            providers_data.get("vision_paid_daily_cap_usd", 1.00)),
        vision_paid_total_cap_usd=float(
            providers_data.get("vision_paid_total_cap_usd", 10.00)),
        vision_paid_unknown_call_floor_usd=float(
            router_data.get("vision_paid_unknown_call_floor_usd", 0.005)),
        vision_paid_price_per_mtok={
            str(k): float(v)
            for k, v in (_get(router_data, "vision_paid_price_per_mtok")
                         or dict(DEFAULT_PRICE_PER_MTOK)).items()
        },
    )
    local_model = LocalModelSettings(
        candidates=_as_str_list(local_data.get("candidates"), []),
        text=str(local_data.get("text", "auto")),
        vision=str(local_data.get("vision", "auto")),
        keep_alive=str(local_data.get("keep_alive", "5m")),
        vision_keep_alive=str(local_data.get("vision_keep_alive", "0")),
        max_concurrency=int(local_data.get("max_concurrency", 1)),
        ollama_url=str(local_data.get("ollama_url", "http://127.0.0.1:11434")),
        enabled=bool(local_data.get("enabled", False)),
    )
    privacy = PrivacySettings(
        blocklist_apps=tuple(str(a) for a in _as_str_list(privacy_data.get("blocklist_apps"), [])),
        redact=tuple(str(a) for a in _as_str_list(
            privacy_data.get("redact"),
            ["api_key", "token", "password", "card", "email", "phone"],
        )),
        debug_capture=bool(privacy_data.get("debug_capture", False)),
    )
    vision = VisionSettings(
        provider=str(vision_data.get("provider", "cloud")),
        max_px=int(vision_data.get("max_px", 1280)),
        quality=int(vision_data.get("quality", 70)),
        max_bytes=int(router_data.get("vision_max_bytes", 4_000_000)),
    )
    voice = VoiceSettings(
        stt_engine=str(voice_data.get("stt_engine", "groq")),
        stt_model=str(voice_data.get("stt_model", "small")),
        stt_language=str(voice_data.get("stt_language", "") or ""),
        wake_word=str(voice_data.get("wake_word", "") or ""),
    )
    return RouterConfig(
        providers=providers,
        local_model=local_model,
        repo_root=cfg_path.parent if cfg_path.parent.exists() else REPO_ROOT,
        profile=profile,
        privacy=privacy,
        vision=vision,
        voice=voice,
    )
