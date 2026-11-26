"""SeedLink LAN source (only the local Raspberry Shake)."""
from __future__ import annotations

import time
from typing import Any

from obspy import Stream, UTCDateTime


class SeedLinkSource:
    def __init__(self, cfg: dict[str, Any]):
        self.host = str(cfg["seedlink"]["host"])
        self.port = int(cfg["seedlink"]["port"])
        self.timeout = float(cfg["seedlink"].get("timeout_s", 20))
        self.net = str(cfg["station"]["network"])
        self.sta = str(cfg["station"]["station"])
        self.loc = str(cfg["station"]["location"])
        self.channels = list(cfg["station"]["channels"])

    def _client(self):
        from obspy.clients.seedlink import Client

        return Client(self.host, port=self.port, timeout=self.timeout)

    def get_stream(self, start: Any, end: Any) -> Stream:
        from obspy.clients.seedlink import Client

        client = Client(self.host, port=self.port, timeout=self.timeout)
        try:
            try:
                st = client.get_waveforms(self.net, self.sta, self.loc, "*", UTCDateTime(start), UTCDateTime(end))
            except Exception:
                st = Stream()
            have = {tr.stats.channel for tr in st}
            for channel in self.channels:
                if channel in have:
                    continue
                try:
                    part = client.get_waveforms(self.net, self.sta, self.loc, channel, UTCDateTime(start), UTCDateTime(end))
                    st += part
                except Exception:
                    continue
            if len(st) > 1:
                st.merge(method=1, fill_value="interpolate")
            return st
        finally:
            try:
                client.close()
            except Exception:
                pass

    def info(self) -> str:
        client = self._client()
        try:
            return str(client.get_info())
        finally:
            try:
                client.close()
            except Exception:
                pass

    def check(self, seconds: float = 10.0) -> dict[str, Any]:
        end = UTCDateTime(time.time())
        start = end - float(seconds)
        st = self.get_stream(start, end)
        return {
            "host": self.host,
            "port": self.port,
            "traces": [
                {
                    "id": tr.id,
                    "start": str(tr.stats.starttime),
                    "end": str(tr.stats.endtime),
                    "fs": tr.stats.sampling_rate,
                    "n": len(tr.data),
                    "gap_pct": round(100 * (1 - len(tr.data) / max(1, (tr.stats.endtime - tr.stats.starttime) * tr.stats.sampling_rate)), 2),
                }
                for tr in st
            ],
            "ok": len(st) > 0,
        }
