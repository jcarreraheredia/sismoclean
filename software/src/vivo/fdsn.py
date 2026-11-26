"""Minimal FDSN client for Raspberry Shake, including the expired-cert workaround."""
from __future__ import annotations

import io
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from obspy import Stream, UTCDateTime, read


class NoDataError(RuntimeError):
    pass


class FDSNClient:
    def __init__(self, cfg: dict[str, Any]):
        self.base = str(cfg["fdsn"]["base"]).rstrip("/")
        self.timeout = float(cfg["fdsn"]["timeout_s"])
        self.retries = int(cfg["fdsn"]["retries"])
        self.verify_ssl = bool(cfg["fdsn"].get("verify_ssl", False))
        self.ctx = None if self.verify_ssl else ssl._create_unverified_context()

    def _get(self, path: str, params: dict[str, Any]) -> bytes:
        url = f"{self.base}/{path}?{urllib.parse.urlencode(params, safe=',')}"
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "vivo-v5/1.0"})
                with urllib.request.urlopen(req, context=self.ctx, timeout=self.timeout) as resp:
                    data = resp.read()
                if not data:
                    raise NoDataError("respuesta vacía")
                return data
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="ignore")[:200]
                if exc.code in (204, 404):
                    raise NoDataError(f"HTTP {exc.code}: {body}") from exc
                last = RuntimeError(f"HTTP {exc.code}: {body}")
                if exc.code == 400:
                    break
                time.sleep(min(30, 3 * (attempt + 1)))
            except NoDataError:
                raise
            except Exception as exc:  # network, timeout, TLS
                last = exc
                time.sleep(min(30, 2 * (attempt + 1)))
        raise RuntimeError(f"FDSN falló: {last}")

    def dataselect(
        self,
        network: str,
        station: str,
        location: str,
        channels: str,
        start: Any,
        end: Any,
    ) -> bytes:
        return self._get(
            "dataselect/1/query",
            {
                "net": network,
                "sta": station,
                "loc": location,
                "cha": channels,
                "start": str(UTCDateTime(start)),
                "end": str(UTCDateTime(end)),
            },
        )

    def stream(
        self,
        network: str,
        station: str,
        location: str,
        channels: str,
        start: Any,
        end: Any,
    ) -> Stream:
        raw = self.dataselect(network, station, location, channels, start, end)
        st = read(io.BytesIO(raw))
        if len(st) == 0:
            raise NoDataError("stream vacío")
        return st

    def event_stream(self, station: str, center: Any, half: float, cfg: dict[str, Any], channels: str = "EHZ,ENZ,ENN,ENE") -> Stream:
        loc = "00"
        for item in [cfg["station"], *cfg.get("cluster", [])]:
            if item.get("station") == station:
                loc = str(item.get("location", "00"))
                break
        t0 = UTCDateTime(center) - float(half)
        t1 = UTCDateTime(center) + float(half)
        return self.stream("AM", station, loc, channels, t0, t1)

    def station_text(self, net: str, sta: str) -> str:
        raw = self._get("station/1/query", {"net": net, "sta": sta, "level": "channel", "format": "text"})
        return raw.decode("utf-8", errors="replace")
