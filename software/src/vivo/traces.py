"""Processed event traces, channel metrics and the live preview CSV."""
from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np
from obspy import Stream, Trace, UTCDateTime

from .config import channel_list, sensitivities
from .csvstore import CsvStore, iso
from .signal import (
    Filters,
    gap_pct,
    physical,
    physical_channels,
    raw_trace_rows,
    select_trace,
    trace_metrics,
    trace_rows,
    trim_fill,
)

CHANNEL_COLUMNS = {"EHZ": "EHZ_m_s", "ENE": "ENE_m_s2", "ENN": "ENN_m_s2", "ENZ": "ENZ_m_s2"}
RAW_COLUMNS = {"EHZ": "EHZ_counts", "ENE": "ENE_counts", "ENN": "ENN_counts", "ENZ": "ENZ_counts"}
INSTRUMENTS = {
    "EHZ": ("geophone", "m/s"),
    "ENE": ("accelerometer", "m/s^2"),
    "ENN": ("accelerometer", "m/s^2"),
    "ENZ": ("accelerometer", "m/s^2"),
}


def event_window(cfg: dict[str, Any], onset: Any) -> tuple[UTCDateTime, UTCDateTime]:
    t = UTCDateTime(onset)
    return t - float(cfg["traces"]["pre_s"]), t + float(cfg["traces"]["post_s"])


def write_event_traces(
    store: CsvStore,
    event: dict[str, Any],
    streams: dict[str, Stream],
    cfg: dict[str, Any],
    filters: Filters,
    phase: dict[str, Any] | None = None,
    confirmed_by: list[str] | None = None,
) -> list[str]:
    """Write processed/raw trace CSV and channel metrics for each available station."""
    onset = UTCDateTime(event["utc_onset"])
    t0, t1 = event_window(cfg, onset)
    channels = channel_list(cfg)
    sens = sensitivities(cfg)
    confirmed_by = confirmed_by or []
    phase = phase or {}
    trace_stations: list[str] = []
    channel_rows: list[dict[str, Any]] = []

    for station, stream in streams.items():
        if stream is None or len(stream) == 0:
            continue
        processed = physical_channels(stream, channels, sens, filters, t0, t1, zero_phase=True)
        if not processed:
            continue
        rows = trace_rows(processed, t0, t1, CHANNEL_COLUMNS)
        if rows:
            store.write_trace(event["event_id"], station, rows, raw=False)
            trace_stations.append(station)
        if bool(cfg["traces"].get("raw", True)):
            raw_rows = raw_trace_rows(stream, channels, t0, t1)
            if raw_rows:
                store.write_trace(event["event_id"], station, raw_rows, raw=True)

        for channel in channels:
            tr = select_trace(stream, channel)
            if tr is None:
                continue
            trimmed = trim_fill(tr, t0, t1)
            data = physical(trimmed, sens.get(channel, 1.0), filters, zero_phase=True)
            metrics = trace_metrics(data)
            instrument, units = INSTRUMENTS.get(channel, ("unknown", ""))
            is_phase_station = station == phase.get("station")
            channel_rows.append(
                {
                    "event_id": event["event_id"],
                    "station": station,
                    "channel": channel,
                    "instrument": instrument,
                    "units": units,
                    "sensitivity": sens.get(channel, ""),
                    "sampling_rate": tr.stats.sampling_rate,
                    "n_samples": len(trimmed.data),
                    "gap_pct": gap_pct(trimmed, t0, t1),
                    "peak": f"{metrics['peak']:.8g}",
                    "rms": f"{metrics['rms']:.8g}",
                    "snr": metrics["snr"],
                    "trigger": "1" if (station == cfg["station"]["station"] or station in confirmed_by) and channel == "EHZ" else "0",
                    "p_prob": f"{phase.get('p', 0):.4f}" if is_phase_station else "",
                    "s_prob": f"{phase.get('s', 0):.4f}" if is_phase_station else "",
                    "p_pick_utc": iso(phase.get("p_pick")) if is_phase_station else "",
                    "s_pick_utc": iso(phase.get("s_pick")) if is_phase_station else "",
                }
            )
    if channel_rows:
        store.upsert_channels(channel_rows)
    if trace_stations:
        event["trace_stations"] = "|".join(sorted(set(trace_stations)))
    return trace_stations


class LiveBuffer:
    """Small in-memory ring buffer for the HTML live view. Never archived."""

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.fs = float(cfg["station"]["fs"])
        self.minutes = float(cfg["traces"].get("live_minutes", 5.0))
        self.channels = channel_list(cfg)
        self.parts: dict[str, deque[tuple[UTCDateTime, np.ndarray]]] = {ch: deque() for ch in self.channels}
        self.end = None

    def add(self, stream: Stream) -> None:
        if stream is None or len(stream) == 0:
            return
        for channel in self.channels:
            tr = select_trace(stream, channel)
            if tr is None:
                continue
            self.parts[channel].append((tr.stats.starttime, np.asarray(tr.data, dtype=float)))
            self.end = max(self.end, tr.stats.endtime) if self.end is not None else tr.stats.endtime
        self._trim()

    def _trim(self) -> None:
        if self.end is None:
            return
        cutoff = self.end - (self.minutes + 1.0) * 60.0
        for channel in self.channels:
            while self.parts[channel] and self.parts[channel][0][0] + len(self.parts[channel][0][1]) / self.fs < cutoff:
                self.parts[channel].popleft()

    def as_stream(self, start: UTCDateTime, end: UTCDateTime) -> Stream:
        out = Stream()
        n = int(round((end - start) * self.fs))
        if n <= 0:
            return out
        for channel in self.channels:
            arr = np.zeros(n, dtype=float)
            for t_start, data in self.parts[channel]:
                offset = int(round((t_start - start) * self.fs))
                a0 = max(0, offset)
                b0 = min(n, offset + len(data))
                s0 = max(0, -offset)
                if b0 > a0:
                    arr[a0:b0] = data[s0 : s0 + (b0 - a0)]
            tr = Trace(data=arr)
            tr.stats.update(
                {
                    "network": self.cfg["station"]["network"],
                    "station": self.cfg["station"]["station"],
                    "location": self.cfg["station"]["location"],
                    "channel": channel,
                    "sampling_rate": self.fs,
                    "starttime": start,
                }
            )
            out.append(tr)
        return out

    def write_view(self, store: CsvStore, filters: Filters) -> bool:
        if self.end is None:
            return False
        end = self.end
        start = end - self.minutes * 60.0
        stream = self.as_stream(start, end)
        channels = channel_list(self.cfg)
        processed = physical_channels(stream, channels, sensitivities(self.cfg), filters, start, end, zero_phase=True)
        if not processed:
            return False
        # 50 Hz is enough for a 2-20 Hz display and keeps the CSV small.
        n = int(round((end - start) * 50.0))
        if n <= 0:
            return False
        arrays = {}
        for channel, (t_start, data) in processed.items():
            ds = np.asarray(data, dtype=float)[::2]
            arr = np.zeros(n, dtype=float)
            m = min(n, len(ds))
            arr[:m] = ds[:m]
            arrays[channel] = arr
        rows = []
        for i in range(n):
            row = {"utc": iso(start + i / 50.0)}
            for channel in channels:
                row[channel] = f"{arrays[channel][i]:.8g}" if channel in arrays else ""
            rows.append(row)
        store.write_live(rows)
        return True
