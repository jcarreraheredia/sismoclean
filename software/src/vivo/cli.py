"""Command line interface for vivo-v5."""
from __future__ import annotations

import argparse
import copy
import functools
import http.server
import json
import os
import platform
import signal
import socketserver
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml
from obspy import UTCDateTime

from . import __version__
from .config import DEFAULT_CONFIG, EXAMPLE_CONFIG, ROOT, load_config, resolve, sensitivities
from .csvstore import disk_free_gb, iso, parse_utc, utc_now
from .engine import Engine, VERSION
from .fdsn import FDSNClient, NoDataError
from .seedlink import SeedLinkSource


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _cfg(args: argparse.Namespace) -> dict[str, Any]:
    cfg = load_config(args.config)
    if getattr(args, "data_dir", None):
        cfg["paths"]["data_dir"] = args.data_dir
    return cfg


def _reset_data_dir(data_dir: Path) -> None:
    """Remove only the generated CSV/trace files, never config or code."""
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in ("eventos.csv", "eventos_historial.csv", "canales.csv", "bloques.csv", "health.csv", "live.csv"):
        (data_dir / name).unlink(missing_ok=True)
    for sub in ("trazas", "trazas_raw"):
        folder = data_dir / sub
        if folder.exists():
            for path in folder.glob("*"):
                if path.is_file():
                    path.unlink(missing_ok=True)


def _print_header(title: str) -> None:
    print()
    print(title)
    print("=" * len(title))


def _ok(flag: bool) -> str:
    return "OK" if flag else "FALLA"


# ----------------------------------------------------------------------
# setup / preflight
# ----------------------------------------------------------------------
def cmd_setup(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    host = args.host
    port = args.port
    if host is None:
        try:
            host = input("IP o nombre del Raspberry Shake [rs.local]: ").strip() or "rs.local"
        except EOFError:
            host = "rs.local"
    if port is None:
        try:
            raw = input("Puerto SeedLink [18000]: ").strip()
            port = int(raw or "18000")
        except (EOFError, ValueError):
            port = 18000
    if not args.test:
        try:
            ans = input("¿Probar la conexión ahora? [s/N]: ").strip().lower()
            args.test = ans in ("s", "si", "sí", "y", "yes")
        except EOFError:
            args.test = False
    raw: dict[str, Any] = {}
    target = Path(args.config) if args.config else DEFAULT_CONFIG
    if target.exists():
        try:
            raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        except Exception:
            raw = {}
    raw.setdefault("seedlink", {})
    raw["seedlink"]["host"] = host
    raw["seedlink"]["port"] = int(port)
    try:
        raw["seedlink"]["timeout_s"] = 20
    except Exception:
        pass
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"Configuración escrita en: {target}")
    print(f"  Shake: {host}:{port}")
    if args.test:
        test_cfg = load_config(target)
        src = SeedLinkSource(test_cfg)
        print("Probando SeedLink (10 s) ...")
        result = src.check(seconds=10)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if not result.get("ok"):
            print("No llegaron datos. Revisa que estés en la red del Shake y que la IP sea correcta.")
            return 1
    print("Siguiente paso: ./run.sh preflight --replay")
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    _print_header("PREFLIGHT VIVO-V5")
    failures = 0
    print(f"Versión: {VERSION}")
    print(f"Python: {sys.version.split()[0]} ({platform.machine()})")
    print(f"Raíz: {ROOT}")
    print(f"Config: {cfg['_config_path']}")
    print(f"Datos: {resolve(cfg, 'data_dir')}")
    print(f"Shake: {cfg['seedlink']['host']}:{cfg['seedlink']['port']}")

    py_ok = sys.version_info >= (3, 10)
    print(f"[{_ok(py_ok)}] Python >= 3.10")
    failures += 0 if py_ok else 1

    modules = ["numpy", "scipy", "obspy", "yaml"]
    if cfg["phasenet"].get("enabled", True):
        modules += ["seisbench", "torch"]
    for name in modules:
        try:
            mod = __import__(name)
            ver = getattr(mod, "__version__", "?")
            print(f"[OK] {name} {ver}")
        except Exception as exc:
            print(f"[FALLA] {name}: {type(exc).__name__}: {exc}")
            failures += 1

    data_dir = resolve(cfg, "data_dir")
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        print(f"[OK] escritura en {data_dir}")
        print(f"[OK] espacio libre: {disk_free_gb(data_dir)} GB")
    except Exception as exc:
        print(f"[FALLA] escritura en {data_dir}: {exc}")
        failures += 1

    viewer = resolve(cfg, "viewer_dir")
    for name in ("index.html", "app.js", "style.css"):
        exists = (viewer / name).exists()
        print(f"[{_ok(exists)}] viewer/{name}")
        failures += 0 if exists else 1

    fixtures = resolve(cfg, "fixture_dir")
    fixture_ok = (fixtures / "hour1_RE626.mseed").exists() and (fixtures / "hour1_R53D1.mseed").exists()
    print(f"[{_ok(fixture_ok)}] fixtures de replay en {fixtures}")
    failures += 0 if fixture_ok else 1

    if args.replay or args.full:
        print("\nPrueba offline de detección/veto (fixtures, sin red) ...")
        tmp = tempfile.TemporaryDirectory(prefix="vivo-preflight-")
        test_cfg = copy.deepcopy(cfg)
        test_cfg["paths"]["data_dir"] = str(Path(tmp.name) / "data")
        test_cfg["paths"]["log_dir"] = str(Path(tmp.name) / "logs")
        try:
            eng = Engine(test_cfg)
            result = eng.replay(no_phasenet=True)
            print(f"  triggers={result.get('triggers')} kept={result.get('KEPT', 0)} "
                  f"veto={result.get('VETO_CONFIRMADO', 0)}")
            expected = result.get("triggers") == 60 and result.get("KEPT", 0) == 25
            print(f"[{_ok(expected)}] esperado: triggers=60, kept=25")
            failures += 0 if expected else 1
        except Exception as exc:
            print(f"[FALLA] replay: {type(exc).__name__}: {exc}")
            failures += 1
        finally:
            tmp.cleanup()

    if args.phase or args.full:
        print("\nPrueba PhaseNet (fixture M4.5) ...")
        try:
            eng = Engine(cfg)
            result = eng.phase_test()
            if not result.get("ok"):
                print(f"[FALLA] PhaseNet: {result.get('error')}")
                failures += 1
            else:
                for row in result.get("all", []):
                    print(f"  {row.get('station')} {row.get('mode')}: "
                          f"P={row.get('p', 0):.3f} S={row.get('s', 0):.3f} "
                          f"{row.get('error', '')}")
                ehz = [r for r in result.get("all", []) if r.get("mode") == "ehz_x3" and not r.get("error")]
                valid = any(max(r["p"], r["s"]) >= float(cfg["phasenet"]["threshold"]) for r in ehz)
                print(f"[{_ok(valid)}] EHZ triplicado supera el umbral")
                failures += 0 if valid else 1
        except Exception as exc:
            print(f"[FALLA] PhaseNet: {type(exc).__name__}: {exc}")
            failures += 1

    if args.online or args.full:
        print("\nPrueba de red ...")
        src = SeedLinkSource(cfg)
        try:
            lan = src.check(seconds=10)
            print(f"[{_ok(lan.get('ok'))}] SeedLink {cfg['seedlink']['host']}:{cfg['seedlink']['port']}")
            for row in lan.get("traces", []):
                print(f"    {row['id']} {row['start']} .. {row['end']} n={row['n']}")
            failures += 0 if lan.get("ok") else 1
        except Exception as exc:
            print(f"[FALLA] SeedLink: {type(exc).__name__}: {exc}")
            failures += 1
        fdsn = FDSNClient(cfg)
        center = utc_now() - float(cfg["tiempos"]["atraso_fdsn_s"])
        for station in [cfg["station"]["station"], *[x["station"] for x in cfg["cluster"]]]:
            try:
                st = fdsn.event_stream(station, center, half=60.0, cfg=cfg, channels="EHZ,ENZ,ENN,ENE")
                print(f"[OK] FDSN {station}: {[tr.id for tr in st]}")
            except Exception as exc:
                print(f"[FALLA] FDSN {station}: {type(exc).__name__}: {exc}")
                failures += 1

    print()
    if failures:
        print(f"PREFLIGHT: {failures} problema(s). Corrige lo indicado antes de arrancar.")
        return 1
    print("PREFLIGHT: todo OK.")
    return 0


# ----------------------------------------------------------------------
# checks
# ----------------------------------------------------------------------
def cmd_lan_check(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    src = SeedLinkSource(cfg)
    print(f"SeedLink {cfg['seedlink']['host']}:{cfg['seedlink']['port']} ...")
    try:
        result = src.check(seconds=args.seconds)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


def cmd_fdsn_check(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    client = FDSNClient(cfg)
    center = utc_now() - float(args.atraso)
    print(f"FDSN: {cfg['fdsn']['base']} (ventana de {iso(center)}, atraso {args.atraso:.0f}s)")
    ok_any = False
    for station in [cfg["station"]["station"], *[x["station"] for x in cfg["cluster"]]]:
        try:
            st = client.event_stream(station, center, half=60.0, cfg=cfg, channels="EHZ,ENZ,ENN,ENE")
            ok_any = True
            print(f"[OK] {station}: {len(st)} trazas")
            for tr in st:
                print(f"    {tr.id} {isolate_start(tr)} n={len(tr.data)}")
        except Exception as exc:
            print(f"[FALLA] {station}: {type(exc).__name__}: {exc}")
    return 0 if ok_any else 1


def isolate_start(tr) -> str:
    return iso(tr.stats.starttime)


# ----------------------------------------------------------------------
# replay / tests
# ----------------------------------------------------------------------
def cmd_replay(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    if args.fresh:
        _reset_data_dir(resolve(cfg, "data_dir"))
    print("Replay offline: hour1, 3 estaciones, sin red.")
    eng = Engine(cfg)
    t0 = time.time()
    result = eng.replay(no_phasenet=args.no_phasenet)
    elapsed = time.time() - t0
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"Tiempo: {elapsed:.1f}s")
    print(f"CSV: {resolve(cfg, 'data_dir')}")
    expected = result.get("triggers") == 60 and result.get("KEPT", 0) == 25
    if not expected:
        print("AVISO: no coincide con el benchmark esperado 60/25.")
    if not args.no_phasenet and cfg["phasenet"].get("enabled", True):
        print(f"Alertas PhaseNet: {result.get('alerts', 0)} (benchmark ~4)")
    return 0


def cmd_phase_test(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    print("Prueba PhaseNet M4.5: 3C real vs EHZ triplicado")
    eng = Engine(cfg)
    result = eng.phase_test()
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0 if result.get("ok") else 1


def cmd_confirm_test(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    onset = UTCDateTime(args.onset)
    delay_s = float(utc_now() - onset)
    print(f"Confirmación FDSN para {iso(onset)} (atraso real {delay_s / 60.0:.1f} min).")
    eng = Engine(cfg)
    event = eng.confirm_one(onset)
    print(json.dumps({k: event.get(k) for k in (
        "event_id", "utc_onset", "status", "confirmed_by", "veto_reason",
        "phasenet_station", "phasenet_input", "p_prob", "s_prob",
        "p_pick_utc", "s_pick_utc", "alert", "last_error")}, indent=2, ensure_ascii=False))
    return 0 if event.get("status") in ("KEPT", "VETO_CONFIRMADO", "PENDIENTE") else 1


# ----------------------------------------------------------------------
# live / viewer / status
# ----------------------------------------------------------------------
def cmd_live(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    if args.fresh:
        _reset_data_dir(resolve(cfg, "data_dir"))
    eng = Engine(cfg)
    eng.write_health()
    print(f"VIVO: Shake {cfg['seedlink']['host']}:{cfg['seedlink']['port']} | "
          f"bloque {cfg['tiempos']['bloque_s']}s | atraso FDSN {cfg['tiempos']['atraso_fdsn_s']}s")
    print(f"Datos: {resolve(cfg, 'data_dir')}")
    duration = float(args.duration_min) * 60.0 if args.duration_min else 0
    try:
        eng.live(max_blocks=args.max_bloques, duration_s=duration, no_phasenet=args.no_phasenet)
    except KeyboardInterrupt:
        print("\nDetenido por el usuario.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    eng = Engine(cfg)
    counts = eng.store.counts()
    pending = [e for e in eng.store.events.values() if e.get("status") in ("PROVISIONAL", "PENDIENTE")]
    print(f"VIVO v{VERSION} | {iso(utc_now())}")
    print(f"Datos: {resolve(cfg, 'data_dir')}")
    print(f"Eventos: {len(eng.store.events)} | {counts}")
    print(f"Pendientes: {len(pending)}")
    if pending:
        oldest = min((parse_utc(e['utc_onset']) for e in pending if parse_utc(e['utc_onset'])), default=None)
        print(f"  más antiguo: {iso(oldest)}")
    health = eng.store.read_health()
    if health:
        print(f"Salud: LAN={health.get('last_lan_sample_utc') or '-'} "
              f"FDSN={health.get('last_fdsn_ok_utc') or '-'} "
              f"disco={health.get('disk_free_gb')} GB")
    print(f"Últimos eventos:")
    for event in list(eng.store.events.values())[-args.last:]:
        print(f"  {event.get('utc_onset')} {event.get('status'):16s} "
              f"P={event.get('p_prob') or '-':>6} S={event.get('s_prob') or '-':>6} "
              f"alert={event.get('alert')}")
    return 0


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        super().end_headers()


def cmd_viewer(args: argparse.Namespace) -> int:
    cfg = _cfg(args)
    viewer_dir = resolve(cfg, "viewer_dir")
    if not (viewer_dir / "index.html").exists():
        print(f"FALLA: no existe {viewer_dir / 'index.html'}")
        return 1
    host = args.host
    port = int(args.port)
    handler = functools.partial(_QuietHandler, directory=str(viewer_dir))
    try:
        server = http.server.ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        print(f"FALLA: no se pudo abrir {host}:{port}: {exc}")
        return 1
    print(f"Visor: http://{host}:{port}/")
    print("Solo escucha en localhost. Desde otro PC usa un túnel SSH:")
    print(f"  ssh -L {port}:127.0.0.1:{port} usuario@IP_DEL_PC")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nVisor detenido.")
    finally:
        server.server_close()
    return 0


# ----------------------------------------------------------------------
# argparse
# ----------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vivo", description="vivo-v5: sismógrafo RE626 24/7")
    parser.add_argument("--config", default=None, help="ruta a config.yaml")
    parser.add_argument("--data-dir", default=None, help="carpeta de datos CSV (opcional)")
    parser.add_argument("--version", action="version", version=f"vivo-v5 {VERSION}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("setup", help="configurar IP/puerto del Shake")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--test", action="store_true")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("preflight", help="comprobar instalación y dependencias")
    p.add_argument("--replay", action="store_true", help="probar detección/veto con fixtures")
    p.add_argument("--phase", action="store_true", help="probar PhaseNet con M4.5")
    p.add_argument("--online", action="store_true", help="probar SeedLink y FDSN")
    p.add_argument("--full", action="store_true", help="replay + phase + online")
    p.set_defaults(func=cmd_preflight)

    p = sub.add_parser("lan-check", help="probar el Shake en la LAN")
    p.add_argument("--seconds", type=float, default=10.0)
    p.set_defaults(func=cmd_lan_check)

    p = sub.add_parser("fdsn-check", help="probar FDSN con atraso de 70 min")
    p.add_argument("--atraso", type=float, default=4200.0)
    p.set_defaults(func=cmd_fdsn_check)

    p = sub.add_parser("replay", help="replay offline hour1 60/25")
    p.add_argument("--no-phasenet", action="store_true")
    p.add_argument("--fresh", action="store_true", help="borrar CSV/trazas generadas antes del replay")
    p.set_defaults(func=cmd_replay)

    p = sub.add_parser("phase-test", help="probar PhaseNet M4.5")
    p.set_defaults(func=cmd_phase_test)

    p = sub.add_parser("confirm-test", help="probar la confirmación FDSN de un evento")
    p.add_argument("--onset", required=True, help="UTC, ej. 2026-10-19T10:00:00")
    p.set_defaults(func=cmd_confirm_test)

    p = sub.add_parser("live", help="bucle 24/7")
    p.add_argument("--max-bloques", type=int, default=0)
    p.add_argument("--duration-min", type=float, default=0)
    p.add_argument("--no-phasenet", action="store_true")
    p.add_argument("--fresh", action="store_true")
    p.set_defaults(func=cmd_live)

    p = sub.add_parser("viewer", help="servidor HTML local")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p.set_defaults(func=cmd_viewer)

    p = sub.add_parser("status", help="resumen de eventos y salud")
    p.add_argument("--last", type=int, default=10)
    p.set_defaults(func=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)
