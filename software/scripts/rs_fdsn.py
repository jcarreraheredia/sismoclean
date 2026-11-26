import io
import urllib3
import requests
from obspy import UTCDateTime, Stream, read

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

FDSN_URL = "https://fdsnws.raspberryshake.org/fdsnws/dataselect/1/query"

def dataselect(network, station, location, channel, starttime, endtime, timeout=15):
    params = {
        "net": network,
        "sta": station,
        "loc": location,
        "cha": channel,
        "starttime": UTCDateTime(starttime).isoformat(),
        "endtime": UTCDateTime(endtime).isoformat(),
    }
    try:
        resp = requests.get(FDSN_URL, params=params, verify=False, timeout=timeout)
        if resp.status_code == 200:
            return read(io.BytesIO(resp.content))
        return Stream()
    except Exception:
        return Stream()
