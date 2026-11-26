"""PhaseNet stage: real 3C accelerometer and validated EHZ fallback."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
from obspy import Stream, UTCDateTime

from .config import ROOT
from .signal import Filters, prep_phasenet_3c, prep_phasenet_ehz


class PhaseNetRunner:
    def __init__(self, cfg: dict[str, Any], filters: Filters):
        self.cfg = cfg
        self.filters = filters
        self.threshold = float(cfg["phasenet"]["threshold"])
        self.half = float(cfg["phasenet"]["half_window_s"])
        self.model_name = str(cfg["phasenet"].get("model", "original"))
        self._model = None
        self.last_error = ""
        cache = Path(cfg["phasenet"].get("cache_dir", "vendor/models"))
        if not cache.is_absolute():
            cache = ROOT / cache
        # Only point SeisBench at the bundled cache when it actually contains weights.
        if cache.exists():
            os.environ.setdefault("SEISBENCH_CACHE_ROOT", str(cache))
        try:
            import torch

            torch.set_num_threads(max(1, min(2, os.cpu_count() or 1)))
        except Exception:
            pass

    @property
    def available(self) -> bool:
        return self._model is not None

    def load(self) -> bool:
        if self._model is not None:
            return True
        try:
            import seisbench.models as sbm

            self._model = sbm.PhaseNet.from_pretrained(self.model_name)
            self._model.eval()
            self.last_error = ""
            return True
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self._model = None
            return False

    def _predict(self, stream: Stream) -> dict[str, Any]:
        pred = self._model.annotate(stream)
        out: dict[str, Any] = {}
        for name in ("PhaseNet_P", "PhaseNet_S"):
            tr = pred.select(channel=name)
            if len(tr) == 0:
                out[name] = {"prob": 0.0, "pick": ""}
                continue
            data = np.asarray(tr[0].data, dtype=float)
            idx = int(np.argmax(data)) if data.size else 0
            t = tr[0].stats.starttime + idx / float(tr[0].stats.sampling_rate)
            out[name] = {"prob": float(data[idx]) if data.size else 0.0, "pick": t}
        return out

    def analyze(self, stream: Stream, station: str, center: Any) -> dict[str, Any]:
        if not self.load():
            return {"station": station, "mode": "", "error": self.last_error, "p": 0.0, "s": 0.0}
        results = []
        for mode in ("3c", "ehz_x3"):
            st = None
            if mode == "3c":
                st = prep_phasenet_3c(stream, center, self.half, self.cfg, self.filters)
            else:
                st = prep_phasenet_ehz(stream, center, self.half, self.cfg, self.filters)
            if st is None:
                results.append({"station": station, "mode": mode, "error": "sin datos suficientes", "p": 0.0, "s": 0.0})
                continue
            try:
                pred = self._predict(st)
                p = float(pred["PhaseNet_P"]["prob"])
                s = float(pred["PhaseNet_S"]["prob"])
                results.append(
                    {
                        "station": station,
                        "mode": mode,
                        "p": p,
                        "s": s,
                        "p_pick": pred["PhaseNet_P"]["pick"],
                        "s_pick": pred["PhaseNet_S"]["pick"],
                        "error": "",
                    }
                )
            except Exception as exc:
                results.append({"station": station, "mode": mode, "error": f"{type(exc).__name__}: {exc}", "p": 0.0, "s": 0.0})
        return {"station": station, "mode": "compare", "results": results}

    def compare(self, streams: dict[str, Stream], stations: list[str], center: Any) -> dict[str, Any]:
        all_results: list[dict[str, Any]] = []
        for station in stations:
            stream = streams.get(station)
            if stream is None:
                continue
            result = self.analyze(stream, station, center)
            all_results.extend(result.get("results", []))
        valid = [r for r in all_results if not r.get("error")]
        if not valid:
            return {
                "ok": False,
                "error": all_results[0]["error"] if all_results else "PhaseNet sin resultados",
                "all": all_results,
                "p": 0.0,
                "s": 0.0,
                "station": "",
                "input": "",
                "alert": False,
            }
        # Prefer the highest P or S probability.  Ties go to EHZ because it is
        # the path validated on the M4.5 benchmark.
        best = max(valid, key=lambda r: (max(r["p"], r["s"]), 1 if r["mode"] == "ehz_x3" else 0))
        alert = max(best["p"], best["s"]) >= self.threshold
        return {
            "ok": True,
            "error": "",
            "all": all_results,
            "p": best["p"],
            "s": best["s"],
            "p_pick": best.get("p_pick"),
            "s_pick": best.get("s_pick"),
            "station": best["station"],
            "input": best["mode"],
            "alert": alert,
        }
