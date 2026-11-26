"""vivo_v3/medir_retardo.py — mide el retardo real de archivo FDSN (puerto 443).

Sondea ventanas [ahora-atraso, ahora-atraso+bloque] para RE626/R2A1F/R53D1
y dice si el veto diferido 5-10 min es viable o si hay que usar 2 niveles (~1h).

Uso Linux:
  python3 vivo_v3/medir_retardo.py
  python3 vivo_v3/medir_retardo.py --rapido
  python3 vivo_v3/medir_retardo.py --atrasos 10,20,40,70 --bloque 60

Sale: vivo_v3/logs/medicion_retardo.json + recomendacion en pantalla.
No toca el puerto 18000. Solo HTTPS 443 (igual que scripts/rs_fdsn.py).
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT / "scripts"))

from rs_fdsn import dataselect  # noqa: E402  (verify=False interno por cert expirado RS)


def fmt_utc(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def medir(estaciones, atrasos_min, bloque_s):
    from datetime import timedelta
    ahora = datetime.now(timezone.utc).replace(microsecond=0)
    filas = []
    for sta in estaciones:
        for atraso in atrasos_min:
            t1 = ahora - timedelta(minutes=atraso)
            t0 = t1 - timedelta(seconds=bloque_s)
            s0, s1 = fmt_utc(t0), fmt_utc(t1)
            try:
                data, url = dataselect("AM", sta, "00", "EHZ", s0, s1)
                filas.append({"sta": sta, "atraso_min": atraso, "ok": True,
                              "bytes": len(data), "t0": s0, "t1": s1})
                print(f"  OK   {sta} atraso={atraso}min bloque={bloque_s}s bytes={len(data)} [{s0} -> {s1}]")
            except Exception as e:
                filas.append({"sta": sta, "atraso_min": atraso, "ok": False,
                              "error": str(e)[:220], "t0": s0, "t1": s1})
                print(f"  FAIL {sta} atraso={atraso}min: {str(e)[:150]}")
    return filas


def recomendar(filas):
    ok = {}
    for f in filas:
        if f["ok"]:
            ok.setdefault(f["sta"], []).append(f["atraso_min"])
    ret_min = {s: min(v) for s, v in ok.items()}
    print("\n== Retardo minimo con datos por estacion ==")
    for s in ["RE626", "R2A1F", "R53D1"]:
        print(f"  {s}: {ret_min.get(s, 'SIN DATOS en los atrasos probados')}")
    peores = [ret_min.get(s, 10**9) for s in ["R2A1F", "R53D1"]]
    peor = max(peores) if peores else 10**9
    print("\n== Recomendacion ==")
    if peor <= 12:
        rec = (f"DIRECTO viable: el cluster responde con {peor}min de atraso. "
               "Pon tiempos.atraso_fdsn_s = (peor+2)*60 en config_vivo.yaml "
               "y el veto sale en 5-12 min.")
    else:
        rec = ("2 NIVELES obligatorio: FDSN sigue con ~1h de retardo. "
               "Usa alerta PROVISIONAL inmediata (RE626 LAN) + confirmacion "
               "vetada diferida (atraso_fdsn_s: 3600). Ver vivo_v3/README.md.")
    print(rec)
    return {"retardo_min_por_estacion": ret_min, "recomendacion": rec}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--atrasos", default="10,20,40,70",
                    help="lista de atrasos en minutos a probar")
    ap.add_argument("--bloque", type=int, default=60)
    ap.add_argument("--rapido", action="store_true",
                    help="solo prueba 10 y 70 min")
    ap.add_argument("--estaciones", default="RE626,R2A1F,R53D1")
    a = ap.parse_args()
    atrasos = [10, 70] if a.rapido else [int(x) for x in a.atrasos.split(",")]
    estaciones = [s.strip() for s in a.estaciones.split(",")]
    print(f"== vivo_v3 medir_retardo (443/HTTPS) bloque={a.bloque}s ==")
    filas = medir(estaciones, atrasos, a.bloque)
    rec = recomendar(filas)
    out = BASE / "logs" / "medicion_retardo.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    json.dump({"bloque_s": a.bloque, "filas": filas, **rec},
              open(out, "w"), indent=2)
    print(f"\nOK {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
