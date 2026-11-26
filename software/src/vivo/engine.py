"""Core orchestration: live blocks, 70-minute confirmation, replay and tests."""
from __future__ import annotations

import csv
import os
import time
from pathlib import Path
from typing import Any

from obspy import Stream, UTCDateTime, read

from .config import (
    ROOT,
    channel_list,
    cluster_cfg,
    ensure_dirs,
    load_config,
    resolve,
    sensitivities,
    station_cfg,
)
from .csvstore import CsvStore, disk_free_gb, event_id, iso, parse_utc, utc_now
from .fdsn import FDSNClient, NoDataError
from .phasenet_stage import PhaseNetRunner
from .seedlink import SeedLinkSource
from .signal import (
    Filters,
    coverage,
    detect_trace,
    select_trace,
    trim_fill,
    triggers_for_station,
)
from .traces import LiveBuffer, event_window, write_event_traces

VERSION = "5.0.0"


class Engine:
    def __init__(self, cfg: dict[str, Any] | None = None):
        self.cfg = cfg or load_config()
        ensure_dirs(self.cfg)
        self.data_dir = resolve(self.cfg, "data_dir")
        self.store = CsvStore(self.data_dir)
        self.filters = Filters(self.cfg)
        self.fdsn = FDSNClient(self.cfg)
        self.seedlink = SeedLinkSource(self.cfg)
        self.phasenet = PhaseNetRunner(self.cfg, self.filters) if self.cfg["phasenet"].get("enabled", True) else None
        self.live_buffer = LiveBuffer(self.cfg)
        self.station = str(self.cfg["station"]["station"])
        self.clean_stations = [str(x["station"]) for x in cluster_cfg(self.cfg)]
        self.last_lan_sample = ""
        self.last_fdsn_ok = ""
        self.last_error = ""
        self.phasenet_ok = False
        self.viewer_ok = True
        self._started = utc_now()

    # ------------------------------------------------------------------
    # events and blocks
    # ------------------------------------------------------------------
    def _existing_onset(self, onset: UTCDateTime, tolerance: float = 0.5) -> dict[str, Any] | None:
        for event in self.store.events.values():
            t = parse_utc(event.get("utc_onset"))
            if t is not None and abs(t - onset) <= tolerance:
                return event
        return None

    def make_event(self, onset: UTCDateTime, end: UTCDateTime, now: UTCDateTime) -> dict[str, Any]:
        eid = event_id(self.station, onset)
        base = eid
        n = 1
        while eid in self.store.events:
            eid = f"{base}_{n}"
            n += 1
        due = onset + float(self.cfg["tiempos"]["atraso_fdsn_s"])
        return {
            "event_id": eid,
            "utc_onset": iso(onset),
            "utc_detect": iso(now),
            "utc_end": iso(end),
            "status": "PROVISIONAL",
            "station": self.station,
            "prov_on": iso(onset),
            "prov_off": iso(end),
            "confirm_due_utc": iso(due),
            "attempts": "0",
            "confirmed_by": "",
            "veto_reason": "",
            "phasenet_station": "",
            "phasenet_input": "",
            "p_prob": "",
            "s_prob": "",
            "p_pick_utc": "",
            "s_pick_utc": "",
            "alert": "0",
            "latency_s": "",
            "trace_stations": "",
            "created_utc": iso(now),
            "updated_utc": iso(now),
            "last_error": "",
        }

    def process_block(self, stream: Stream, block_start: UTCDateTime, block_end: UTCDateTime, now: UTCDateTime | None = None) -> dict[str, Any]:
        now = now or utc_now()
        self.live_buffer.add(stream)
        triggers = triggers_for_station(stream, self.station, self.filters, self.cfg["deteccion"])
        triggers = [(a, b) for a, b in triggers if block_start <= a < block_end]
        created = 0
        for onset, end in triggers:
            if self._existing_onset(onset) is not None:
                continue
            event = self.make_event(onset, end, now)
            self.store.upsert_event(event, "trigger STA/LTA", save=False)
            # Save a first local trace immediately; it is what the 30 s viewer shows.
            write_event_traces(self.store, event, {self.station: stream}, self.cfg, self.filters)
            self.store.upsert_event(event, save=False)
            created += 1
        if triggers:
            self.store.save_events()
        self.last_lan_sample = iso(now)
        self.live_buffer.write_view(self.store, self.filters)
        self.store.append_block(
            {
                "utc_start": iso(block_start),
                "utc_end": iso(block_end),
                "station": self.station,
                "triggers": len(triggers),
                "kept": 0,
                "veto": 0,
                "errors": 0,
                "lan_ok": 1 if len(stream) else 0,
                "fdsn_ok": 0,
            }
        )
        return {"triggers": len(triggers), "created": created, "traces": len(stream)}

    # ------------------------------------------------------------------
    # confirmation
    # ------------------------------------------------------------------
    def fetch_confirmation_streams(self, onset: UTCDateTime) -> tuple[dict[str, Stream], list[str]]:
        streams: dict[str, Stream] = {}
        errors: list[str] = []
        for station in [self.station, *self.clean_stations]:
            try:
                st = self.fdsn.event_stream(station, onset, half=60.0, cfg=self.cfg, channels="EHZ,ENZ,ENN,ENE")
                if len(st) == 0:
                    errors.append(f"{station}: stream vacío")
                    continue
                streams[station] = st
            except NoDataError as exc:
                errors.append(f"{station}: sin datos ({exc})")
            except Exception as exc:
                errors.append(f"{station}: {type(exc).__name__}: {exc}")
        if any(s in streams for s in self.clean_stations):
            self.last_fdsn_ok = iso(utc_now())
        return streams, errors

    def _trigger_coincides(
        self,
        clean_triggers: list[tuple[UTCDateTime, UTCDateTime]],
        onset: UTCDateTime,
        end: UTCDateTime,
    ) -> bool:
        tol = float(self.cfg["deteccion"]["tol_onset_s"])
        pad = float(self.cfg["deteccion"]["pad_solape_s"])
        for a, b in clean_triggers:
            if abs(a - onset) <= tol:
                return True
            if a <= end + pad and b >= onset - pad:
                return True
        return False

    def _next_retry(self, event: dict[str, Any], now: UTCDateTime, error: str) -> None:
        attempts = int(event.get("attempts") or 0) + 1
        max_attempts = int(self.cfg["tiempos"]["max_attempts"])
        onset = parse_utc(event.get("utc_onset")) or now
        age_h = float(now - onset) / 3600.0
        event["attempts"] = str(attempts)
        event["last_error"] = error[:500]
        event["updated_utc"] = iso(now)
        if attempts >= max_attempts or age_h >= float(self.cfg["tiempos"]["max_wait_h"]):
            event["status"] = "SIN_DATOS"
            event["veto_reason"] = "sin datos suficientes en estaciones limpias"
            self.store.upsert_event(event, "agotados reintentos FDSN")
            return
        backoff = self.cfg["tiempos"].get("retry_backoff_s", [300, 900, 1800, 3600, 7200])
        delay = float(backoff[min(attempts - 1, len(backoff) - 1)])
        event["status"] = "PENDIENTE"
        event["confirm_due_utc"] = iso(now + delay)
        self.store.upsert_event(event, f"reintento {attempts}: {error[:120]}")

    def confirm_event(self, event: dict[str, Any], streams: dict[str, Stream], now: UTCDateTime | None = None) -> dict[str, Any]:
        now = now or utc_now()
        onset = parse_utc(event.get("utc_onset"))
        if onset is None:
            event["status"] = "SIN_DATOS"
            event["last_error"] = "utc_onset inválido"
            self.store.upsert_event(event, "fecha inválida")
            return event
        end = parse_utc(event.get("utc_end")) or onset
        clean_results: dict[str, dict[str, Any]] = {}
        missing: list[str] = []
        for station in self.clean_stations:
            stream = streams.get(station)
            tr = select_trace(stream, "EHZ") if stream is not None else None
            cov = coverage(tr, onset - 30.0, onset + 30.0) if tr is not None else 0.0
            if tr is None or cov < 0.70:
                missing.append(f"{station}: cobertura {cov:.0%}")
                clean_results[station] = {"valid": False, "coincident": False, "triggers": []}
                continue
            triggers = detect_trace(tr, station, self.filters, self.cfg["deteccion"])
            coincident = self._trigger_coincides(triggers, onset, end)
            clean_results[station] = {"valid": True, "coincident": coincident, "triggers": triggers, "coverage": cov}
            self.last_fdsn_ok = iso(now)

        confirmed = [s for s, r in clean_results.items() if r["valid"] and r["coincident"]]
        all_valid = all(r["valid"] for r in clean_results.values()) and len(clean_results) == len(self.clean_stations)
        if confirmed:
            event["status"] = "KEPT"
            event["confirmed_by"] = "|".join(confirmed)
            event["veto_reason"] = ""
        elif all_valid:
            event["status"] = "VETO_CONFIRMADO"
            event["confirmed_by"] = ""
            event["veto_reason"] = "sin trigger en estaciones limpias"
        else:
            error = "; ".join(missing) or "faltan estaciones limpias"
            event["confirmed_by"] = ""
            event["veto_reason"] = "datos insuficientes"
            self._next_retry(event, now, error)
            # Still persist whatever trace material arrived, for diagnostics.
            write_event_traces(self.store, event, streams, self.cfg, self.filters)
            self.store.upsert_event(event, save=False)
            self.store.save_events()
            return event

        event["updated_utc"] = iso(now)
        event["latency_s"] = f"{float(now - onset):.1f}"
        event["last_error"] = "; ".join(missing)
        self.store.upsert_event(event, f"confirmación: {event['status']}", save=False)

        phase: dict[str, Any] = {}
        if event["status"] == "KEPT" and self.phasenet is not None:
            stations = [s for s in self.cfg["phasenet"].get("compare_stations", []) if s in streams] or confirmed
            phase = self.phasenet.compare(streams, stations, onset)
            self.phasenet_ok = bool(phase.get("ok"))
            if phase.get("ok"):
                event["phasenet_station"] = phase.get("station", "")
                event["phasenet_input"] = phase.get("input", "")
                event["p_prob"] = f"{phase.get('p', 0):.4f}"
                event["s_prob"] = f"{phase.get('s', 0):.4f}"
                event["p_pick_utc"] = iso(phase.get("p_pick"))
                event["s_pick_utc"] = iso(phase.get("s_pick"))
                event["alert"] = "1" if phase.get("alert") else "0"
            else:
                event["last_error"] = f"PhaseNet: {phase.get('error', 'sin resultado')}"
                event["alert"] = "0"
        else:
            event["alert"] = "0"

        self.store.upsert_event(event, "resultado final", save=False)
        write_event_traces(self.store, event, streams, self.cfg, self.filters, phase=phase, confirmed_by=confirmed)
        self.store.upsert_event(event)
        return event

    def process_pending(self, force: bool = False, limit: int = 10) -> dict[str, int]:
        now = utc_now()
        pending = self.store.pending(now if not force else None)
        if force:
            pending = [e for e in self.store.events.values() if e.get("status") in ("PROVISIONAL", "PENDIENTE")]
        stats = {"processed": 0, "kept": 0, "veto": 0, "pending": 0, "error": 0}
        for event in pending[:limit]:
            onset = parse_utc(event.get("utc_onset"))
            attempts = int(event.get("attempts") or 0)
            if onset is None:
                event["status"] = "SIN_DATOS"
                event["last_error"] = "utc_onset inválido"
                self.store.upsert_event(event, "fecha inválida")
                stats["error"] += 1
                continue
            if attempts >= int(self.cfg["tiempos"]["max_attempts"]) or (now - onset) / 3600.0 >= float(self.cfg["tiempos"]["max_wait_h"]):
                event["status"] = "SIN_DATOS"
                event["last_error"] = "agotados intentos/ventana FDSN"
                self.store.upsert_event(event, "agotado")
                stats["error"] += 1
                continue
            streams, errors = self.fetch_confirmation_streams(onset)
            if not any(s in streams for s in self.clean_stations):
                self._next_retry(event, now, "; ".join(errors) or "sin estaciones limpias")
                stats["pending"] += 1
                continue
            event = self.confirm_event(event, streams, now)
            stats["processed"] += 1
            if event.get("status") == "KEPT":
                stats["kept"] += 1
            elif event.get("status") == "VETO_CONFIRMADO":
                stats["veto"] += 1
            elif event.get("status") == "PENDIENTE":
                stats["pending"] += 1
            else:
                stats["error"] += 1
        self.write_health()
        return stats

    def confirm_one(self, onset: UTCDateTime) -> dict[str, Any]:
        event = self._existing_onset(onset, tolerance=0.01)
        if event is None:
            event = self.make_event(onset, onset + 1.0, utc_now())
            event["confirm_due_utc"] = iso(utc_now())
            self.store.upsert_event(event, "prueba de confirmación")
        streams, errors = self.fetch_confirmation_streams(onset)
        if not streams:
            self._next_retry(event, utc_now(), "; ".join(errors))
            return event
        event = self.confirm_event(event, streams, utc_now())
        return event

    # ------------------------------------------------------------------
    # health / live
    # ------------------------------------------------------------------
    def write_health(self) -> None:
        pending = [e for e in self.store.events.values() if e.get("status") in ("PROVISIONAL", "PENDIENTE")]
        oldest = min((parse_utc(e.get("utc_onset")) for e in pending if parse_utc(e.get("utc_onset"))), default=None)
        self.store.write_health(
            {
                "utc": iso(utc_now()),
                "last_lan_sample_utc": self.last_lan_sample,
                "last_fdsn_ok_utc": self.last_fdsn_ok,
                "pending": len(pending),
                "oldest_pending_utc": iso(oldest),
                "disk_free_gb": disk_free_gb(self.data_dir),
                "phasenet_ok": 1 if self.phasenet_ok else 0,
                "viewer_ok": 1 if self.viewer_ok else 0,
                "version": VERSION,
            }
        )

    def preload_phasenet(self) -> bool:
        if self.phasenet is None:
            return False
        self.phasenet_ok = self.phasenet.load()
        return self.phasenet_ok

    def cleanup(self) -> int:
        """Delete old trace files according to retention.*; never touches event CSV."""
        now = time.time()
        removed = 0
        plans = [
            (self.store.traces_dir, "*.csv", float(self.cfg["retention"].get("trace_days", 30))),
            (self.store.raw_dir, "*.csv.gz", float(self.cfg["retention"].get("raw_trace_days", 7))),
        ]
        for folder, pattern, days in plans:
            if days <= 0 or not folder.exists():
                continue
            cutoff = now - days * 86400.0
            for path in folder.glob(pattern):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                        removed += 1
                except OSError:
                    continue
        # Remove leftover temporary files after a crash.
        for folder in (self.data_dir, self.store.traces_dir, self.store.raw_dir):
            for path in folder.glob("*.tmp"):
                try:
                    if now - path.stat().st_mtime > 3600:
                        path.unlink()
                except OSError:
                    continue
        return removed

    def live(self, max_blocks: int = 0, duration_s: float = 0, no_phasenet: bool = False) -> None:
        if no_phasenet:
            self.phasenet = None
        if not no_phasenet and self.phasenet is not None:
            if not self.preload_phasenet():
                print(f"AVISO: PhaseNet no cargó: {self.phasenet.last_error}")
                print("       El pipeline sigue detectando y confirmando; se reintentará en cada evento.")
        block_s = float(self.cfg["tiempos"]["bloque_s"])
        margin = float(self.cfg["tiempos"]["margen_s"])
        post_s = float(self.cfg["traces"]["post_s"])
        next_end = UTCDateTime(time.time())
        started = time.time()
        blocks = 0
        last_cleanup = 0.0
        while True:
            if max_blocks and blocks >= max_blocks:
                break
            if duration_s and (time.time() - started) >= duration_s:
                break
            if time.time() - last_cleanup > 3600.0:
                self.cleanup()
                last_cleanup = time.time()
            # Wait post_s before detecting: a trigger needs 20 s of future
            # signal for its event trace.  The next slot is contiguous, so no
            # trigger is lost and no window overlaps.
            block_end = next_end - post_s
            block_start = block_end - block_s
            fetch_start = block_start - margin
            fetch_end = next_end
            try:
                st = self.seedlink.get_stream(fetch_start, fetch_end)
            except Exception as exc:
                self.last_error = f"SeedLink: {type(exc).__name__}: {exc}"
                print(f"ERROR SeedLink: {self.last_error}")
                st = Stream()
            now = utc_now()
            if len(st) == 0:
                self.write_health()
                print(f"sin datos SeedLink en {iso(fetch_start)} .. {iso(fetch_end)}")
            else:
                stats = self.process_block(st, block_start, block_end, now)
                if stats["triggers"]:
                    print(f"bloque {iso(block_start)}: {stats['triggers']} triggers, {stats['created']} nuevos")
                self.process_pending(limit=4)
                self.write_health()
            blocks += 1
            next_end = next_end + block_s
            now_epoch = time.time()
            if next_end.timestamp < now_epoch:
                # Do not accumulate a backlog after a network stall.
                print(f"AVISO: retraso de {now_epoch - next_end.timestamp:.0f}s; salto al bloque actual")
                next_end = UTCDateTime(now_epoch)
            sleep_s = max(0.0, next_end.timestamp - time.time())
            if sleep_s:
                time.sleep(min(sleep_s, 5.0))
                while time.time() < next_end.timestamp:
                    time.sleep(min(1.0, next_end.timestamp - time.time()))
        self.write_health()

    # ------------------------------------------------------------------
    # offline replay and validation
    # ------------------------------------------------------------------
    def _fixture(self, name: str) -> Path:
        return resolve(self.cfg, "fixture_dir") / name

    def _read_with_3c(self, base: str) -> Stream:
        st = read(str(self._fixture(base)))
        extra = self._fixture(base.replace(".mseed", "_3C.mseed"))
        if extra.exists():
            st += read(str(extra))
        if len(st) > 1:
            st.merge(method=1, fill_value="interpolate")
        return st

    def replay(self, no_phasenet: bool = False) -> dict[str, Any]:
        if no_phasenet:
            self.phasenet = None
        re626 = read(str(self._fixture("hour1_RE626.mseed")))
        streams: dict[str, Stream] = {"RE626": re626}
        for station in self.clean_stations:
            streams[station] = self._read_with_3c(f"hour1_{station}.mseed")
        tr = select_trace(re626, "EHZ")
        if tr is None:
            raise RuntimeError("fixture hour1_RE626.mseed no contiene EHZ")
        triggers = detect_trace(tr, "RE626", self.filters, self.cfg["deteccion"])
        # The benchmark uses the whole hour, not live blocks.
        for onset, end in triggers:
            event = self.make_event(onset, end, onset + 1.0)
            self.store.upsert_event(event, "replay trigger")
            event = self.confirm_event(event, streams, onset + float(self.cfg["tiempos"]["atraso_fdsn_s"]))
        counts = self.store.counts()
        alerts = sum(1 for e in self.store.events.values() if e.get("status") == "KEPT" and e.get("alert") == "1")
        self.write_health()
        return {"triggers": len(triggers), **counts, "alerts": alerts}

    def phase_test(self) -> dict[str, Any]:
        """Validate the M4.5 benchmark: real 3C vs EHZ triplicated."""
        onset = UTCDateTime("2026-09-15T23:45:27.332Z")
        streams = {}
        for station in self.clean_stations:
            streams[station] = self._read_with_3c(f"ev_local_close_M45_20260915_{station}.mseed")
        if self.phasenet is None:
            return {"error": "PhaseNet deshabilitado"}
        result = self.phasenet.compare(streams, self.clean_stations, onset)
        return result
