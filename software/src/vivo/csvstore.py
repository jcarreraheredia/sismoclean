"""CSV persistence.

The scientific data is deliberately stored in CSV files (plus optional gzipped
CSV for raw event windows).  There is no SQLite, Firebase or other database.
"""
from __future__ import annotations

import csv
import gzip
import os
import shutil
import tempfile
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from obspy import UTCDateTime

EVENT_COLUMNS = [
    "event_id",
    "utc_onset",
    "utc_detect",
    "utc_end",
    "status",
    "station",
    "prov_on",
    "prov_off",
    "confirm_due_utc",
    "attempts",
    "confirmed_by",
    "veto_reason",
    "phasenet_station",
    "phasenet_input",
    "p_prob",
    "s_prob",
    "p_pick_utc",
    "s_pick_utc",
    "alert",
    "latency_s",
    "trace_stations",
    "created_utc",
    "updated_utc",
    "last_error",
]

CHANNEL_COLUMNS = [
    "event_id",
    "station",
    "channel",
    "instrument",
    "units",
    "sensitivity",
    "sampling_rate",
    "n_samples",
    "gap_pct",
    "peak",
    "rms",
    "snr",
    "trigger",
    "p_prob",
    "s_prob",
    "p_pick_utc",
    "s_pick_utc",
]

TRACE_COLUMNS = ["utc", "EHZ_m_s", "ENE_m_s2", "ENN_m_s2", "ENZ_m_s2"]
RAW_TRACE_COLUMNS = ["utc", "EHZ_counts", "ENE_counts", "ENN_counts", "ENZ_counts"]

HISTORY_COLUMNS = ["utc", "event_id", "old_status", "new_status", "reason"]
BLOCK_COLUMNS = [
    "utc_start",
    "utc_end",
    "station",
    "triggers",
    "kept",
    "veto",
    "errors",
    "lan_ok",
    "fdsn_ok",
]
HEALTH_COLUMNS = [
    "utc",
    "last_lan_sample_utc",
    "last_fdsn_ok_utc",
    "pending",
    "oldest_pending_utc",
    "disk_free_gb",
    "phasenet_ok",
    "viewer_ok",
    "version",
]
LIVE_COLUMNS = ["utc", "EHZ", "ENE", "ENN", "ENZ"]


def utc_now() -> UTCDateTime:
    return UTCDateTime(datetime.now(timezone.utc))


def iso(value: Any) -> str:
    """UTC ISO string with milliseconds and trailing Z."""
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        try:
            value = UTCDateTime(value)
        except Exception:
            return value
    t = value if isinstance(value, UTCDateTime) else UTCDateTime(value)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(t.microsecond / 1000):03d}Z"


def parse_utc(value: Any) -> UTCDateTime | None:
    if value is None or value == "":
        return None
    try:
        return UTCDateTime(value)
    except Exception:
        return None


def event_id(station: str, onset: Any) -> str:
    t = onset if isinstance(onset, UTCDateTime) else UTCDateTime(onset)
    ms = int(t.microsecond / 1000)
    return f"{station}_{t.strftime('%Y%m%dT%H%M%S')}_{ms:03d}Z"


def _atomic_path(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    return Path(tmp)


def _replace(tmp: Path, path: Path) -> None:
    """Atomic replace, with a fallback for OneDrive/antivirus locks on Windows."""
    for attempt in range(6):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 5:
                break
            time.sleep(0.08 * (attempt + 1))
    try:
        path.unlink(missing_ok=True)
        os.replace(tmp, path)
        return
    except PermissionError:
        # Last resort for a locked target: copy over it.  On Linux the first
        # os.replace normally succeeds and remains atomic.
        shutil.copyfile(tmp, path)
        tmp.unlink(missing_ok=True)


def atomic_write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    tmp = _atomic_path(path)
    try:
        with tmp.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in fieldnames})
            fh.flush()
            os.fsync(fh.fileno())
        _replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    tmp = _atomic_path(path)
    try:
        with tmp.open("w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        _replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


class CsvStore:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.traces_dir = self.data_dir / "trazas"
        self.raw_dir = self.data_dir / "trazas_raw"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.traces_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.data_dir / "eventos.csv"
        self.history_path = self.data_dir / "eventos_historial.csv"
        self.channels_path = self.data_dir / "canales.csv"
        self.blocks_path = self.data_dir / "bloques.csv"
        self.health_path = self.data_dir / "health.csv"
        self.live_path = self.data_dir / "live.csv"
        self._lock = threading.RLock()
        self.events: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self.channels: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.load()
        # Create the headers immediately so the viewer never starts with 404s.
        if not self.events_path.exists():
            self.save_events()
        if not self.channels_path.exists():
            self.save_channels()
        if not self.live_path.exists():
            self.write_live([])
        if not self.health_path.exists():
            atomic_write_csv(self.health_path, HEALTH_COLUMNS, [])

    # ---------- loading ----------
    def load(self) -> None:
        with self._lock:
            self.events = OrderedDict()
            if self.events_path.exists():
                with self.events_path.open("r", encoding="utf-8", newline="") as fh:
                    for row in csv.DictReader(fh):
                        if row.get("event_id"):
                            self.events[row["event_id"]] = {k: row.get(k, "") for k in EVENT_COLUMNS}
            self.channels = {}
            if self.channels_path.exists():
                with self.channels_path.open("r", encoding="utf-8", newline="") as fh:
                    for row in csv.DictReader(fh):
                        key = (row.get("event_id", ""), row.get("station", ""), row.get("channel", ""))
                        if key[0]:
                            self.channels[key] = {k: row.get(k, "") for k in CHANNEL_COLUMNS}

    # ---------- events ----------
    def save_events(self) -> None:
        with self._lock:
            rows = sorted(self.events.values(), key=lambda r: r.get("utc_onset", ""))
            atomic_write_csv(self.events_path, EVENT_COLUMNS, rows)

    def upsert_event(self, event: dict[str, Any], reason: str = "", save: bool = True) -> None:
        with self._lock:
            eid = event["event_id"]
            old = self.events.get(eid)
            old_status = old.get("status", "") if old else ""
            merged = {k: event.get(k, "") for k in EVENT_COLUMNS}
            if old:
                for k in EVENT_COLUMNS:
                    if merged.get(k, "") == "" and old.get(k, "") != "":
                        merged[k] = old[k]
            self.events[eid] = merged
            if save:
                self.save_events()
            if not old or old_status != merged.get("status"):
                self.append_history(eid, old_status, merged.get("status", ""), reason or "state change")

    def append_history(self, eid: str, old_status: str, new_status: str, reason: str) -> None:
        new_file = not self.history_path.exists()
        with self.history_path.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=HISTORY_COLUMNS)
            if new_file:
                writer.writeheader()
            writer.writerow(
                {
                    "utc": iso(utc_now()),
                    "event_id": eid,
                    "old_status": old_status,
                    "new_status": new_status,
                    "reason": reason,
                }
            )
            fh.flush()

    def pending(self, now: Any = None) -> list[dict[str, Any]]:
        now_t = now if isinstance(now, UTCDateTime) else UTCDateTime(now) if now else utc_now()
        out = []
        for event in self.events.values():
            if event.get("status") not in ("PROVISIONAL", "PENDIENTE"):
                continue
            due = parse_utc(event.get("confirm_due_utc"))
            if due is None or due <= now_t:
                out.append(event)
        return out

    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for event in self.events.values():
            status = event.get("status", "?")
            counts[status] = counts.get(status, 0) + 1
        return counts

    # ---------- channels ----------
    def save_channels(self) -> None:
        with self._lock:
            rows = sorted(self.channels.values(), key=lambda r: (r.get("event_id", ""), r.get("station", ""), r.get("channel", "")))
            atomic_write_csv(self.channels_path, CHANNEL_COLUMNS, rows)

    def upsert_channels(self, rows: Iterable[dict[str, Any]]) -> None:
        with self._lock:
            for row in rows:
                key = (row.get("event_id", ""), row.get("station", ""), row.get("channel", ""))
                if key[0] and key[1] and key[2]:
                    self.channels[key] = {k: row.get(k, "") for k in CHANNEL_COLUMNS}
            self.save_channels()

    # ---------- traces and viewer ----------
    def trace_path(self, eid: str, station: str, raw: bool = False) -> Path:
        base = self.raw_dir if raw else self.traces_dir
        suffix = ".csv.gz" if raw else ".csv"
        return base / f"{eid}_{station}{suffix}"

    def write_trace(self, eid: str, station: str, rows: list[dict[str, Any]], raw: bool = False) -> Path:
        path = self.trace_path(eid, station, raw=raw)
        columns = RAW_TRACE_COLUMNS if raw else TRACE_COLUMNS
        if raw:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            with gzip.open(tmp, "wt", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                for row in rows:
                    writer.writerow({k: row.get(k, "") for k in columns})
            _replace(tmp, path)
        else:
            atomic_write_csv(path, columns, rows)
        return path

    def write_live(self, rows: list[dict[str, Any]]) -> None:
        atomic_write_csv(self.live_path, LIVE_COLUMNS, rows)

    def append_block(self, row: dict[str, Any]) -> None:
        new_file = not self.blocks_path.exists()
        with self.blocks_path.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=BLOCK_COLUMNS)
            if new_file:
                writer.writeheader()
            writer.writerow({k: row.get(k, "") for k in BLOCK_COLUMNS})
            fh.flush()

    def write_health(self, row: dict[str, Any]) -> None:
        atomic_write_csv(self.health_path, HEALTH_COLUMNS, [row])

    def read_health(self) -> dict[str, Any]:
        if not self.health_path.exists():
            return {}
        with self.health_path.open("r", encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        return rows[-1] if rows else {}


def disk_free_gb(path: Path) -> float:
    try:
        usage = os.statvfs(path)
    except AttributeError:
        import shutil
        return round(shutil.disk_usage(path).free / 1e9, 2)
    return round((usage.f_bavail * usage.f_frsize) / 1e9, 2)
