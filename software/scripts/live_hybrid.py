"""vivo_v3/live_hybrid.py — veto multi-estacion sin puerto 18000 externo.

Arquitectura:
  RE626 propia  <- LAN SeedLink <SHAKE_LAN_IP>:18000 (obspy, MiniSEED, no cruza firewall U)
  R2A1F + R53D1 <- FDSN HTTPS 443 (scripts/rs_fdsn.py, cert verify=False ya conocido)
  NTP del sistema para alinear (tol veto 5s >> error NTP esperado <0.2s)

Dos niveles (porque FDSN archiva con ~1h de retardo, ver SESION.md):
  Nivel 1 PROVISIONAL: trigger RE626 LAN ahora mismo (umbral estricto config_vivo.yaml).
  Nivel 2 CONFIRMADA:  el mismo epoch E = ahora-atraso se re-procesa con cluster
                       FDSN -> KEPT (coincide>=1 limpia) o VETO_CONFIRMADO.

Modos:
  --modo sim      : replay offline de data/raw_mseed/<tag>_*.mseed en bloques.
                    Valida la cadena sin red. Ej: --sim-tag hour1
  --modo hibrido  : real. RE626 por SeedLink LAN + cluster por FDSN. (default)
  --modo solo-lan : debug, solo RE626 LAN sin FDSN.

Ejemplos Linux:
  python3 vivo_v3/live_hybrid.py --modo sim --sim-tag hour1
  python3 vivo_v3/medir_retardo.py --rapido
  python3 vivo_v3/live_hybrid.py --modo hibrido --shake-ip 192.168.1.50 --atraso 3600
  python3 vivo_v3/live_hybrid.py --modo hibrido --shake-ip 192.168.1.50 --atraso 600  # si medir_retardo demuestra <10min

Logs: vivo_v3/logs/alertas.jsonl (una linea por alerta) y bloques.jsonl (resumen por bloque).
"""
import argparse
import io
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import yaml
from scipy.signal import butter, sosfilt, iirnotch, tf2sos

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT / "scripts"))

CFG_BASE = yaml.safe_load(open(ROOT / "config.yaml"))
CFG_VIVO = yaml.safe_load(open(BASE / "config_vivo.yaml"))

FS = float(CFG_BASE["estacion_objetivo"]["fs"])
SENS = float(CFG_BASE["estacion_objetivo"]["sens_counts_per_ms"])
SOS_HP = butter(CFG_BASE["prefiltro"]["orden_hp"], CFG_BASE["prefiltro"]["highpass"],
                btype="highpass", fs=FS, output="sos")
SOS_N = [tf2sos(*iirnotch(w0=f, Q=CFG_BASE["prefiltro"]["notch_Q"], fs=FS))
         for f in CFG_BASE["prefiltro"]["notch"]]
lo, hi = CFG_BASE["deteccion"]["banda"]
SOS_DET = butter(CFG_BASE["deteccion"]["orden_bp"], [lo, hi], btype="bandpass", fs=FS, output="sos")
THR = CFG_BASE["deteccion"]["umbrales"]
TOL = CFG_BASE["veto"]["tol_onset_s"]
PAD = CFG_BASE["veto"]["pad_solape_s"]
PROV_ON = float(CFG_VIVO["alerta"]["provisional_on"])
PROV_OFF = float(CFG_VIVO["alerta"]["provisional_off"])
# Margen de calentamiento por bloque en streaming: el filtro SOS + STA/LTA
# (LTA 20 s) necesitan historia. Se procesa [E0-MARGEN, E1] y solo se emiten
# onsets >= E0. Sin esto, cada corte de bloque genera falsos de borde
# (en la prueba hour1 daba 17 kept en vez de ~25).
MARGEN_S = 60


# ---------- cadena (identica a run_cluster.py) ----------
def light(x):
    y = sosfilt(SOS_HP, np.asarray(x, float) - np.mean(x))
    for s in SOS_N:
        y = sosfilt(s, y)
    return sosfilt(SOS_DET, y)


def detect(sta, x, on=None, off=None):
    from obspy.signal.trigger import classic_sta_lta, trigger_onset
    cft = classic_sta_lta(light(x), int(CFG_BASE["deteccion"]["sta_s"] * FS),
                          int(CFG_BASE["deteccion"]["lta_s"] * FS))
    sta_thr = THR.get(sta, THR) if isinstance(THR, dict) else{}
    on = on if on is not None else (sta_thr.get("on",3.2) if isinstance(sta_thr, dict) else 3.2)
    off = off if off is not None else (sta_thr.get("off",1.4) if isinstance(sta_thr,dict) else 1.4)
    return trigger_onset(cft, on, off)


def a_tiempo(trigs, t0_epoch):
    """pasa triggers muestra->epoch UTC."""
    return [(t0_epoch + s / FS, t0_epoch + e / FS) for s, e in trigs]


def detect_bloque(sta, data_con_margen, t_margen_epoch, e0_epoch, e1_epoch,
                  on=None, off=None):
    """Detecta sobre [margen..fin] pero solo devuelve onsets dentro de [E0, E1].

    Elimina transitorios de borde de sosfilt y calentamiento de STA/LTA.
    """
    trigs = a_tiempo(detect(sta, data_con_margen, on, off), t_margen_epoch)
    return [(a, b) for a, b in trigs if a >= e0_epoch and a < e1_epoch]


def veto(re626, cleaners):
    kept, vetoed = [], []
    for r in re626:
        ok = any(abs(r[0] - c[0]) <= TOL and
                 max(r[0] - PAD, c[0] - PAD) <= min(r[1] + PAD, c[1] + PAD)
                 for lst in cleaners for c in lst)
        (kept if ok else vetoed).append(r)
    return kept, vetoed


# ---------- fuentes ----------
def bloque_seedlink_lan(host, puerto, t0_epoch, t1_epoch, timeout=20):
    """Pide [t0,t1] al Shake LOCAL por SeedLink (puerto 18000 en LAN, no internet).

    No usa data.raspberryshake.org:18000 (bloqueado por la U).
    """
    from obspy import UTCDateTime
    from obspy.clients.seedlink import Client as SLClient
    c = SLClient(host, port=puerto, timeout=timeout)
    st = c.get_waveforms(CFG_VIVO["shake_lan"]["red"], CFG_VIVO["shake_lan"]["sta"],
                         CFG_VIVO["shake_lan"]["loc"], CFG_VIVO["shake_lan"]["cha"],
                         UTCDateTime(t0_epoch), UTCDateTime(t1_epoch))
    tr = st[0]
    return tr.data.copy(), float(tr.stats.starttime), tr.stats.sampling_rate


def bloque_fdsn(net, sta, loc, cha, t0_iso, t1_iso, timeout=90):
    """Pide [t0,t1] por FDSN 443 (permitido). Devuelve (data, t0_epoch)."""
    import io
    from rs_fdsn import dataselect
    from obspy import read as obspy_read
    res = dataselect(net, sta, loc, cha, t0_iso, t1_iso)
    if not res or len(res) < 2:
        return None
    raw, _url = res[0], res[1]
    if not raw:
        return None
    st = obspy_read(io.BytesIO(raw))
    if len(st) == 0:
        return None
    tr = st[0]
    return tr.data.copy(), float(tr.stats.starttime)

def iso(epoch):
    from obspy import UTCDateTime
    return str(UTCDateTime(epoch))


def check_ntp():
    """Avisa si el reloj no esta sincronizado (veto tolera 5s, pero avisar es gratis)."""
    for cmd in (["timedatectl", "status"], ["chronyc", "tracking"]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                txt = r.stdout
                print(f"[ntp] {' '.join(cmd)}:\n" + "\n".join(txt.splitlines()[:6]))
                return
        except Exception:
            continue
    print("[ntp] no se pudo verificar (instala chrony). El veto tolera 5s, pero sincroniza el reloj.")


# ---------- bucles ----------
def run_sim(tag, bloque_s, log_dir, con_phasenet=False):
    """Replay offline: divide hour1/ev_* en bloques y simula provisional + confirmada."""
    from obspy import read
    from obspy import UTCDateTime
    print(f"[sim] tag={tag} bloque={bloque_s}s")
    trs = {}
    for sta in ["RE626", "R2A1F", "R53D1"]:
        fp = ROOT / "data" / "raw_mseed" / f"{tag}_{sta}.mseed"
        if not fp.exists():
            print(f"[sim] FALTA {fp}")
            return 2
        trs[sta] = read(str(fp))[0]
    t0 = min(float(tr.stats.starttime) for tr in trs.values())
    t0_sta = {sta: float(trs[sta].stats.starttime) for sta in trs}
    # fin comun (todas cubren ~1h; se usa el minimo para no salir de rango)
    t_end = min(float(tr.stats.endtime) for tr in trs.values())
    nb = int((t_end - t0) // bloque_s)
    print(f"[sim] inicio={UTCDateTime(t0)} bloques={nb} (offsets: " +
          ", ".join(f"{s} {(t0_sta[s]-t0):+.2f}s" for s in ["RE626", "R2A1F", "R53D1"]) + ")")

    def ventana(sta, e0, e1):
        """Devuelve (data_con_margen, t_margen_epoch) alineada en tiempo absoluto."""
        tr = trs[sta]
        a = int(round((e0 - MARGEN_S - t0_sta[sta]) * FS))
        b = int(round((e1 - t0_sta[sta]) * FS))
        a = max(0, a)
        b = min(len(tr.data), b)
        seg = tr.data[a:b]
        t_margen = t0_sta[sta] + a / FS
        return seg, t_margen

    prov_total, kept_total, veto_total = 0, 0, 0
    m = int(MARGEN_S * FS)
    for b in range(nb):
        eb0 = t0 + b * bloque_s
        eb1 = eb0 + bloque_s
        # Nivel 1: RE626 con umbral provisional estricto (solo onsets en [eb0, eb1])
        seg, t_m = ventana("RE626", eb0, eb1)
        p = detect_bloque("RE626", seg, t_m, eb0, eb1, PROV_ON, PROV_OFF)
        # Nivel 2: veto con umbrales base sobre el MISMO bloque (en sim no hay atraso)
        seg_r, t_mr = ventana("RE626", eb0, eb1)
        r = detect_bloque("RE626", seg_r, t_mr, eb0, eb1)
        seg1, t_m1 = ventana("R2A1F", eb0, eb1)
        c1 = detect_bloque("R2A1F", seg1, t_m1, eb0, eb1)
        seg2, t_m2 = ventana("R53D1", eb0, eb1)
        c2 = detect_bloque("R53D1", seg2, t_m2, eb0, eb1)
        kept, vetoed = veto(r, [c1, c2])
        prov_total += len(p)
        kept_total += len(kept)
        veto_total += len(vetoed)
        for x in p:
            emit(log_dir, {"tipo": "PROVISIONAL", "t": iso(x[0]), "bloque": b})
            print(f"  [b{b}] PROVISIONAL {UTCDateTime(x[0])}")
        for x in kept:
            emit(log_dir, {"tipo": "KEPT", "t": iso(x[0]), "bloque": b})
            print(f"  [b{b}] KEPT {UTCDateTime(x[0])}")
        emit(log_dir, None, bloque={"b": b, "t": iso(eb0), "prov": len(p),
                                    "kept": len(kept), "veto": len(vetoed)}, silent=True)
    print(f"[sim] bloques={nb} provisionales={prov_total} kept={kept_total} veto={veto_total}")
    if tag == "hour1":
        print("[sim] referencia run_cluster.py offline: RE626 60 -> kept 25. "
              "Aqui kept usa los mismos umbrales base; el provisional 3.5/1.5 es "
              "aparte y mas estricto. (El '4' de Fase 8 es despues de PhaseNet.)")
    return 0


def run_hibrido(shake_ip, shake_port, bloque_s, atraso_s, poll_s, max_bloques, log_dir):
    """Real: RE626 LAN ahora (provisional) + epoch E=ahora-atraso con FDSN (confirmada)."""
    from obspy import UTCDateTime
    print(f"[hibrido] shake={shake_ip}:{shake_port} bloque={bloque_s}s atraso={atraso_s}s poll={poll_s}s")
    check_ntp()
    n = 0
    while max_bloques == 0 or n < max_bloques:
        ahora = time.time()
        # --- Nivel 1: RE626 LAN en vivo (con margen, solo onsets del bloque) ---
        try:
            LAN0 = ahora - bloque_s - MARGEN_S
            d_lan, t_lan, _sr = bloque_seedlink_lan(shake_ip, shake_port, LAN0, ahora)
            p = detect_bloque("RE626", d_lan, t_lan, ahora - bloque_s, ahora,
                              PROV_ON, PROV_OFF)
            for x in p:
                emit(log_dir, {"tipo": "PROVISIONAL", "t": iso(x[0])})
                print(f"[PROVISIONAL] {UTCDateTime(x[0])} (RE626 LAN, pendiente veto)")
        except Exception as e:
            print(f"[lan] FAIL SeedLink local {shake_ip}:{shake_port}: {str(e)[:200]}")
            print("      Revisa IP (rs.local o 192.168.x.x), SeedLink activado y misma LAN.")
        # --- Nivel 2: epoch diferido E con veto ---
        E0 = ahora - atraso_s - bloque_s
        E1 = ahora - atraso_s
        try:
            d_re, t_re,*_ = bloque_seedlink_lan(shake_ip, shake_port, E0 - MARGEN_S, E1)
            r = detect_bloque("RE626", d_re, t_re, E0, E1)
            limpias = []
            for cfg in CFG_VIVO["cluster_fdsn"]["estaciones"]:
                try:
                    res_c = bloque_fdsn(cfg["red"], cfg["sta"], cfg["loc"], cfg["cha"], iso(E0 - MARGEN_S), iso(E1))
                    if not res_c:
                        continue
                    d_c, t_c = res_c[0], res_c[1]
                    sta = cfg["sta"]
                    limpias.append(detect_bloque(sta, d_c, t_c, E0, E1))
                    print(f"[fdsn] {sta} [({iso(E0)} -> {iso(E1)})] ok")
                except Exception as e:
                    print(f"[fdsn] {cfg['sta']} FAIL: {str(e)[:150]} (reintenta proximo poll)")
            if limpias:
                kept, vetoed = veto(r, limpias)
                for x in kept:
                    emit(log_dir, {"tipo": "KEPT", "t": iso(x[0]), "epoch": iso(E0)})
                    print(f"[KEPT] {UTCDateTime(x[0])} (coincide cluster, tol {TOL}s)")
                for x in vetoed:
                    emit(log_dir, {"tipo": "VETO_CONFIRMADO", "t": iso(x[0]), "epoch": iso(E0)})
                emit(log_dir, None, bloque={"t": iso(E0), "re626": len(r),
                                            "kept": len(kept), "veto": len(vetoed)}, silent=True)
                print(f"[bloque] E={UTCDateTime(E0)} RE626={len(r)} kept={len(kept)} veto={len(vetoed)}")
            else:
                print("[bloque] sin cluster FDSN este ciclo; los provisionales quedan pendientes.")
        except Exception as e:
            print(f"[bloque] FAIL epoch diferido: {str(e)[:200]}")
        n += 1
        if max_bloques == 0 or n < max_bloques:
            time.sleep(poll_s)
    return 0


def emit(log_dir, alerta, bloque=None, silent=False):
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    if alerta is not None:
        with open(log_dir / "alertas.jsonl", "a") as f:
            f.write(json.dumps(alerta) + "\n")
    if bloque is not None:
        with open(log_dir / "bloques.jsonl", "a") as f:
            f.write(json.dumps(bloque) + "\n")
        if not silent:
            print(bloque)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", default="hibrido", choices=["sim", "hibrido", "solo-lan"])
    ap.add_argument("--sim-tag", default="hour1")
    ap.add_argument("--shake-ip", default=CFG_VIVO["shake_lan"]["host"])
    ap.add_argument("--shake-port", type=int, default=CFG_VIVO["shake_lan"]["seedlink_puerto"])
    ap.add_argument("--bloque", type=int, default=CFG_VIVO["tiempos"]["bloque_s"])
    ap.add_argument("--atraso", type=int, default=CFG_VIVO["tiempos"]["atraso_fdsn_s"])
    ap.add_argument("--poll", type=int, default=CFG_VIVO["tiempos"]["poll_fdsn_s"])
    ap.add_argument("--max-bloques", type=int, default=0, help="0=infinito (servicio)")
    ap.add_argument("--log-dir", default=str(ROOT / CFG_VIVO["salida"]["log_dir"]))
    a = ap.parse_args()
    if a.modo == "sim":
        return run_sim(a.sim_tag, a.bloque, Path(a.log_dir))
    if a.modo == "solo-lan":
        from obspy import UTCDateTime
        check_ntp()
        ahora = time.time()
        d, t, _ = bloque_seedlink_lan(a.shake_ip, a.shake_port,
                                      ahora - a.bloque - MARGEN_S, ahora)
        p = detect_bloque("RE626", d, t, ahora - a.bloque, ahora, PROV_ON, PROV_OFF)
        print(f"[solo-lan] {UTCDateTime(t)} provisionales={len(p)}")
        for x in p:
            print(f"  PROVISIONAL {UTCDateTime(x[0])}")
        return 0
    return run_hibrido(a.shake_ip, a.shake_port, a.bloque, a.atraso, a.poll,
                       a.max_bloques, Path(a.log_dir))


if __name__ == "__main__":
    raise SystemExit(main())
