"""Router configuration loading and validation."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.yaml"


def _simple_yaml_load(path: Path) -> dict[str, Any]:
    """Minimal YAML loader for the flat/nested structure used in config.yaml."""
    result: dict[str, Any] = {}
    current_stack: list[tuple[int, dict[str, Any]]] = [(0, result)]
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("#"):
                    continue
                if not line.strip():
                    continue
                indent = len(line) - len(line.lstrip(" "))
                content = line.strip()
                if content.startswith("-"):
                    # Top-level list item in this minimal form? not expected here
                    continue
                if ":" not in content:
                    continue
                key, value = content.split(":", 1)
                key = key.strip()
                value = value.strip()
                while current_stack and current_stack[-1][0] >= indent and len(current_stack) > 1:
                    current_stack.pop()
                parent = current_stack[-1][1]
                if value == "":
                    new_dict: dict[str, Any] = {}
                    parent[key] = new_dict
                    current_stack.append((indent + 2, new_dict))
                else:
                    # Parse scalar
                    if value.startswith("[") and value.endswith("]"):
                        items_str = value[1:-1]
                        if items_str.strip() == "":
                            parent[key] = []
                        else:
                            items = [i.strip().strip("'\"") for i in items_str.split(",")]
                            parent[key] = items
                    elif value.lower() == "true":
                        parent[key] = True
                    elif value.lower() == "false":
                        parent[key] = False
                    elif value.isdigit():
                        parent[key] = int(value)
                    else:
                        try:
                            # float?
                            if "." in value:
                                parent[key] = float(value)
                            else:
                                raise ValueError
                        except Exception:
                            parent[key] = value.strip("'\"")
    except FileNotFoundError:
        return result
    return result


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


@dataclass(frozen=True)
class LocalModelSettings:
    candidates: list[str]
    text: str
    vision: str
    keep_alive: str
    vision_keep_alive: str
    max_concurrency: int
    ollama_url: str


@dataclass(frozen=True)
class RouterConfig:
    providers: RouterSettings
    local_model: LocalModelSettings
    repo_root: Path


def _get_nested(cfg: dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = cfg
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def load_config(path: Path | None = None) -> RouterConfig:
    cfg_path = path or DEFAULT_CONFIG_PATH
    data = _simple_yaml_load(cfg_path) if cfg_path.exists() else {}
    providers_data = _get_nested(data, "providers") or {}
    local_data = _get_nested(data, "local_model") or {}
    chain = providers_data.get("chain") or ["zen_free", "go", "ollama"]
    if not isinstance(chain, list):
        chain = [str(x) for x in chain]
    providers = RouterSettings(
        chain=chain,
        allow_go_runtime=bool(providers_data.get("allow_go_runtime", False)),
        allow_paid_runtime=bool(providers_data.get("allow_paid_runtime", False)),
        allow_free_models_for_personal_data=bool(providers_data.get("allow_free_models_for_personal_data", False)),
        zen_base_url=providers_data.get("zen_base_url", "https://opencode.ai/zen/v1"),
        go_base_url=providers_data.get("go_base_url", "https://opencode.ai/zen/go/v1"),
        discovery_interval_s=int(providers_data.get("discovery_interval_s", 3600)),
        max_calls_per_minute=int(providers_data.get("max_calls_per_minute", 12)),
        benchmark_ranking_path=str(providers_data.get("benchmark_ranking_path", "brain/router/benchmark_ranking.json")),
    )
    local_model = LocalModelSettings(
        candidates=local_data.get("candidates") or [],
        text=str(local_data.get("text", "auto")),
        vision=str(local_data.get("vision", "auto")),
        keep_alive=str(local_data.get("keep_alive", "5m")),
        vision_keep_alive=str(local_data.get("vision_keep_alive", "0")),
        max_concurrency=int(local_data.get("max_concurrency", 1)),
        ollama_url=str(local_data.get("ollama_url", "http://127.0.0.1:11434")),
    )
    return RouterConfig(providers=providers, local_model=local_model, repo_root=REPO_ROOT)
