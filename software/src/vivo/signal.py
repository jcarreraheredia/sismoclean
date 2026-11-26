"""Signal processing shared by detection, traces and PhaseNet input."""
from __future__ import annotations

from typing import Any

import numpy as np
from obspy import Stream, Trace, UTCDateTime
from obspy.signal.trigger import classic_sta_lta, trigger_onset
from scipy.signal import butter, iirnotch, sosfilt, sosfiltfilt, tf2sos


class Filters:
    def __init__(self, cfg: dict[str, Any]):
        det = cfg["deteccion"]
        self.fs = float(cfg["station"]["fs"])
        self.sos_hp = butter(int(det["orden_hp"]), float(det["highpass"]), btype="highpass", fs=self.fs, output="sos")
        self.sos_notch = [
            tf2sos(*iirnotch(w0=float(f), Q=float(det["notch_q"]), fs=self.fs))
            for f in det["notch"]
        ]
        self.sos_bp = butter(
            int(det["orden_bp"]),
            [float(det["banda"][0]), float(det["banda"][1])],
            btype="bandpass",
            fs=self.fs,
            output="sos",
        )
        # PhaseNet's benchmark input is a 1-45 Hz zero-phase bandpass, not the
        # 2-20 Hz detection display chain.  Keep the two paths separate.
        self.sos_phasenet = butter(4, [1.0, 45.0], btype="bandpass", fs=self.fs, output="sos")

    def _apply(self, x: np.ndarray, filt_fn) -> np.ndarray:
        y = filt_fn(self.sos_hp, np.asarray(x, dtype=float))
        for sos in self.sos_notch:
            y = filt_fn(sos, y)
        return filt_fn(self.sos_bp, y)

    def detection(self, x: np.ndarray) -> np.ndarray:
        return self._apply(x, sosfilt)

    def display(self, x: np.ndarray) -> np.ndarray:
        return self._apply(x, sosfiltfilt)

    def phasenet(self, x: np.ndarray) -> np.ndarray:
        # ObsPy's ``filter(..., zerophase=True)`` applies two causal passes
        # (forward, then backward) without filtfilt padding.  Match it exactly
        # so the M4.5/hour1 PhaseNet benchmark remains reproducible.
        y = sosfilt(self.sos_phasenet, np.asarray(x, dtype=float))
        y = np.flip(y)
        y = sosfilt(self.sos_phasenet, y)
        return np.flip(y)


def detect_trace(tr: Trace, station: str, filters: Filters, thresholds: dict[str, Any]) -> list[tuple[UTCDateTime, UTCDateTime]]:
    """STA/LTA over a full trace; returns absolute UTC onset/end tuples."""
    if tr is None or len(tr.data) < int(filters.fs * 2):
        return []
    x = filters.detection(tr.data)
    umbrales = thresholds.get("umbrales", thresholds)
    thr = umbrales.get(station, {"on": 3.0, "off": 1.5})
    cft = classic_sta_lta(x, int(float(thresholds.get("sta_s", 1.0)) * filters.fs), int(float(thresholds.get("lta_s", 20.0)) * filters.fs))
    onsets = trigger_onset(cft, float(thr["on"]), float(thr["off"]))
    t0 = tr.stats.starttime
    return [(t0 + float(a) / filters.fs, t0 + float(b) / filters.fs) for a, b in onsets]


def triggers_for_station(
    stream: Stream,
    station: str,
    filters: Filters,
    thresholds: dict[str, Any],
) -> list[tuple[UTCDateTime, UTCDateTime]]:
    tr = select_trace(stream, "EHZ")
    return detect_trace(tr, station, filters, thresholds) if tr is not None else []


def select_trace(stream: Stream | None, channel: str) -> Trace | None:
    if not stream:
        return None
    st = stream.select(channel=channel)
    if len(st) == 0:
        return None
    st = st.copy()
    if len(st) > 1:
        st.merge(method=1, fill_value="interpolate")
    return st[0]


def trim_fill(tr: Trace, t0: Any, t1: Any) -> Trace:
    out = tr.copy()
    out.trim(UTCDateTime(t0), UTCDateTime(t1), pad=True, fill_value=0)
    return out


def coverage(tr: Trace | None, t0: Any, t1: Any) -> float:
    if tr is None:
        return 0.0
    span = float(UTCDateTime(t1) - UTCDateTime(t0))
    if span <= 0:
        return 0.0
    expected = span * float(tr.stats.sampling_rate)
    if expected <= 0:
        return 0.0
    return min(1.0, len(tr.data) / expected)


def gap_pct(tr: Trace | None, t0: Any, t1: Any) -> float:
    return round(100.0 * (1.0 - coverage(tr, t0, t1)), 2)


def physical(tr: Trace, sensitivity: float, filters: Filters, zero_phase: bool = True) -> np.ndarray:
    data = np.asarray(tr.data, dtype=float)
    data = data - float(np.mean(data))
    if data.size == 0:
        return data
    try:
        processed = filters.display(data) if zero_phase else filters.detection(data)
    except Exception:
        processed = data
    return processed / float(sensitivity or 1.0)


def physical_channels(
    stream: Stream,
    channels: list[str],
    sensitivities: dict[str, float],
    filters: Filters,
    t0: Any,
    t1: Any,
    zero_phase: bool = True,
) -> dict[str, tuple[Any, np.ndarray]]:
    out: dict[str, tuple[Any, np.ndarray]] = {}
    for channel in channels:
        tr = select_trace(stream, channel)
        if tr is None:
            continue
        tr = trim_fill(tr, t0, t1)
        out[channel] = (tr.stats.starttime, physical(tr, sensitivities.get(channel, 1.0), filters, zero_phase=zero_phase))
    return out


def trace_rows(
    processed: dict[str, tuple[Any, np.ndarray]],
    t0: Any,
    t1: Any,
    columns: dict[str, str],
) -> list[dict[str, Any]]:
    """Wide CSV rows for the viewer: utc + one column per requested channel."""
    if not processed:
        return []
    start = UTCDateTime(t0)
    end = UTCDateTime(t1)
    fs = 100.0
    n = int(round((end - start) * fs))
    if n <= 0:
        return []
    arrays = {}
    for channel, (t_start, data) in processed.items():
        offset = int(round((UTCDateTime(t_start) - start) * fs))
        arr = np.zeros(n, dtype=float)
        src = np.asarray(data, dtype=float)
        a0 = max(0, offset)
        b0 = min(n, offset + len(src))
        s0 = max(0, -offset)
        if b0 > a0:
            arr[a0:b0] = src[s0 : s0 + (b0 - a0)]
        arrays[channel] = arr
    rows = []
    for i in range(n):
        row = {"utc": _iso(start + i / fs)}
        for channel, column in columns.items():
            if channel in arrays:
                row[column] = f"{arrays[channel][i]:.8g}"
            else:
                row[column] = ""
        rows.append(row)
    return rows


def raw_trace_rows(
    stream: Stream,
    channels: list[str],
    t0: Any,
    t1: Any,
) -> list[dict[str, Any]]:
    start = UTCDateTime(t0)
    end = UTCDateTime(t1)
    fs = 100.0
    n = int(round((end - start) * fs))
    if n <= 0:
        return []
    arrays = {}
    for channel in channels:
        tr = select_trace(stream, channel)
        if tr is None:
            continue
        tr = trim_fill(tr, start, end)
        offset = int(round((tr.stats.starttime - start) * fs))
        arr = np.zeros(n, dtype=float)
        src = np.asarray(tr.data, dtype=float)
        a0 = max(0, offset)
        b0 = min(n, offset + len(src))
        s0 = max(0, -offset)
        if b0 > a0:
            arr[a0:b0] = src[s0 : s0 + (b0 - a0)]
        arrays[channel] = arr
    columns = {"EHZ": "EHZ_counts", "ENE": "ENE_counts", "ENN": "ENN_counts", "ENZ": "ENZ_counts"}
    rows = []
    for i in range(n):
        row = {"utc": _iso(start + i / fs)}
        for channel, column in columns.items():
            row[column] = f"{arrays[channel][i]:.0f}" if channel in arrays else ""
        rows.append(row)
    return rows


def prep_phasenet_3c(stream: Stream, center: Any, half: float, cfg: dict[str, Any], filters: Filters) -> Stream | None:
    """Real 3C input using the accelerometer channels ENZ/ENN/ENE."""
    t0 = UTCDateTime(center) - float(half)
    t1 = UTCDateTime(center) + float(half)
    traces = {}
    for channel in ("ENZ", "ENN", "ENE"):
        tr = select_trace(stream, channel)
        if tr is None:
            return None
        traces[channel] = trim_fill(tr, t0, t1)
    # FDSN can return each component with a slightly different start time.
    # Trim all three to the common overlap before building the model volume.
    common_start = max(tr.stats.starttime for tr in traces.values())
    common_end = min(tr.stats.endtime for tr in traces.values())
    if common_end <= common_start:
        return None
    traces = {ch: trim_fill(tr, common_start, common_end) for ch, tr in traces.items()}
    n = min(len(tr.data) for tr in traces.values())
    if n < 100:
        return None
    out = Stream()
    for channel in ("ENZ", "ENN", "ENE"):
        tr = traces[channel]
        data = np.asarray(tr.data[:n], dtype=float)
        data = data - float(np.mean(data))
        data = filters.phasenet(data)
        data = data / (float(np.max(np.abs(data))) + 1e-12)
        new = Trace(data=data.astype(np.float32))
        new.stats.update(
            {
                "network": "AM",
                "station": tr.stats.station,
                "location": tr.stats.location,
                "channel": channel,
                "sampling_rate": float(cfg["station"]["fs"]),
                "starttime": common_start,
            }
        )
        out.append(new)
    return out


def prep_phasenet_ehz(stream: Stream, center: Any, half: float, cfg: dict[str, Any], filters: Filters) -> Stream | None:
    """Validated fallback: EHZ triplicated into Z/N/E."""
    tr = select_trace(stream, "EHZ")
    if tr is None:
        return None
    t0 = UTCDateTime(center) - float(half)
    t1 = UTCDateTime(center) + float(half)
    tr = trim_fill(tr, t0, t1)
    if len(tr.data) < 100:
        return None
    sens = float(cfg["station"]["sensitivities"].get("EHZ", 1.0))
    data = np.asarray(tr.data, dtype=float)
    data = data - float(np.mean(data))
    data = filters.phasenet(data) / sens
    data = data / (float(np.max(np.abs(data))) + 1e-12)
    out = Stream()
    for channel in ("EHZ", "EHN", "EHE"):
        new = Trace(data=data.astype(np.float32))
        new.stats.update(
            {
                "network": "AM",
                "station": tr.stats.station,
                "location": tr.stats.location,
                "channel": channel,
                "sampling_rate": float(cfg["station"]["fs"]),
                "starttime": tr.stats.starttime,
            }
        )
        out.append(new)
    return out


def trace_metrics(data: np.ndarray) -> dict[str, float]:
    arr = np.asarray(data, dtype=float)
    if arr.size == 0:
        return {"peak": 0.0, "rms": 0.0, "snr": 0.0}
    peak = float(np.max(np.abs(arr)))
    rms = float(np.sqrt(np.mean(arr * arr)))
    return {"peak": peak, "rms": rms, "snr": round(peak / (rms + 1e-12), 2)}


def _iso(value: Any) -> str:
    t = value if isinstance(value, UTCDateTime) else UTCDateTime(value)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(t.microsecond / 1000):03d}Z"
