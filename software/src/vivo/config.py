"""Configuration and paths for vivo-v5.

Everything is intentionally small and explicit: one YAML file, no database.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "config.yaml"
EXAMPLE_CONFIG = ROOT / "config" / "config.example.yaml"

DEFAULTS: dict[str, Any] = {
    "station": {
        "network": "AM",
        "station": "RE626",
        "location": "00",
        "channels": ["EHZ", "ENE", "ENN", "ENZ"],
        "fs": 100.0,
        "sensitivities": {
            "EHZ": 399650000.0,
            "ENE": 384500.0,
            "ENN": 384500.0,
            "ENZ": 384500.0,
        },
    },
    "cluster": [
        {"network": "AM", "station": "R2A1F", "location": "00"},
        {"network": "AM", "station": "R53D1", "location": "00"},
    ],
    "seedlink": {"host": "rs.local", "port": 18000, "timeout_s": 20},
    "fdsn": {
        "base": "https://data.raspberryshake.org/fdsnws",
        "verify_ssl": False,
        "timeout_s": 60,
        "retries": 4,
    },
    "tiempos": {
        "bloque_s": 30,
        "margen_s": 30,
        "atraso_fdsn_s": 4200,
        "poll_confirm_s": 60,
        "max_attempts": 12,
        "max_wait_h": 8,
        "retry_backoff_s": [300, 900, 1800, 3600, 7200],
    },
    "deteccion": {
        "highpass": 0.7,
        "notch": [29.79, 18.07, 42.24],
        "notch_q": 30,
        "orden_hp": 2,
        "banda": [2.0, 20.0],
        "orden_bp": 4,
        "sta_s": 1.0,
        "lta_s": 20.0,
        "umbrales": {
            "RE626": {"on": 3.2, "off": 1.4},
            "R2A1F": {"on": 2.8, "off": 1.2},
            "R53D1": {"on": 3.5, "off": 1.5},
        },
        "provisional_on": 3.5,
        "provisional_off": 1.5,
        "tol_onset_s": 5.0,
        "pad_solape_s": 2.0,
    },
    "phasenet": {
        "enabled": True,
        "mode": "compare",
        "threshold": 0.15,
        "half_window_s": 15.0,
        "model": "original",
        "cache_dir": "vendor/models",
        "compare_stations": ["R53D1"],
    },
    "traces": {
        "pre_s": 10.0,
        "post_s": 20.0,
        "raw": True,
        "live_minutes": 5.0,
    },
    "paths": {
        "data_dir": "viewer/data",
        "viewer_dir": "viewer",
        "fixture_dir": "tests/fixtures",
        "log_dir": "logs",
    },
    "retention": {"trace_days": 30, "raw_trace_days": 7, "viewer_events": 1000},
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Load config.yaml, falling back to the example and built-in defaults."""
    candidate = Path(path) if path else DEFAULT_CONFIG
    if not candidate.exists():
        candidate = EXAMPLE_CONFIG
    raw: dict[str, Any] = {}
    if candidate.exists():
        with candidate.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    cfg = _deep_merge(DEFAULTS, raw)
    cfg["_config_path"] = str(candidate)
    cfg["_root"] = str(ROOT)
    return cfg


def resolve(cfg: dict[str, Any], key: str) -> Path:
    value = Path(cfg["paths"][key])
    return value if value.is_absolute() else ROOT / value


def ensure_dirs(cfg: dict[str, Any]) -> None:
    data_dir = resolve(cfg, "data_dir")
    for sub in ("", "trazas", "trazas_raw"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)
    resolve(cfg, "log_dir").mkdir(parents=True, exist_ok=True)
    resolve(cfg, "viewer_dir").mkdir(parents=True, exist_ok=True)


def channel_list(cfg: dict[str, Any]) -> list[str]:
    return list(cfg["station"]["channels"])


def station_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    return cfg["station"]


def cluster_cfg(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    return list(cfg["cluster"])


def sensitivities(cfg: dict[str, Any]) -> dict[str, float]:
    return {k: float(v) for k, v in cfg["station"]["sensitivities"].items()}
