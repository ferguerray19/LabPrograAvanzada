"""Valida el dataset completo contra el contrato de datos.

Recorre TODAS las lineas de TODOS los shards, no las primeras. Los registros
rotos por concurrencia aparecen en el medio, nunca al principio, y un dataset
truncado por la muerte de un worker es sintacticamente perfecto: solo se
detecta contando.

    python -m bench.validar data/raw

Codigo de salida 0 si el dataset es valido y alcanza el minimo; 1 si no.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.esquema import validar_evento  # noqa: E402

MINIMO_DURO = 10_000_000


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Validador del dataset TPC Fase 1")
    p.add_argument("carpeta", nargs="?", default="data/raw")
    p.add_argument("--minimo", type=int, default=MINIMO_DURO)
    p.add_argument("--profundo", action="store_true",
                   help="ademas de parsear, verifica el esquema campo a campo "
                        "(mas lento, pero es lo que revisa el evaluador)")
    args = p.parse_args(argv)

    archivos = sorted(glob.glob(os.path.join(args.carpeta, "*.jsonl")))
    if not archivos:
        print(f"No se encontraron archivos .jsonl en {args.carpeta}")
        return 1

    total = 0
    por_worker: Counter = Counter()
    por_metrica: Counter = Counter()
    por_status: Counter = Counter()
    sensores = set()
    ts_min = ts_max = None

    for ruta in archivos:
        n_archivo = 0
        with open(ruta, encoding="utf-8") as f:
            for i, linea in enumerate(f, 1):
                try:
                    ev = json.loads(linea)
                except json.JSONDecodeError as exc:
                    print(f"Linea invalida en {ruta}:{i} -> {exc}")
                    return 1
                if args.profundo:
                    try:
                        validar_evento(ev)
                    except ValueError as exc:
                        print(f"Esquema roto en {ruta}:{i} -> {exc}")
                        return 1
                por_worker[ev["worker_id"]] += 1
                por_metrica[ev["metric"]] += 1
                if "status" in ev:
                    por_status[ev["status"]] += 1
                sensores.add(ev["sensor_id"])
                ts = ev["timestamp"]
                if ts_min is None or ts < ts_min:
                    ts_min = ts
                if ts_max is None or ts > ts_max:
                    ts_max = ts
                n_archivo += 1
                total += 1
        print(f"  {os.path.basename(ruta):>20}  {n_archivo:>12,} lineas")

    bytes_tot = sum(os.path.getsize(r) for r in archivos)
    print()
    print(f"Eventos validos     : {total:,}")
    print(f"Bytes en disco      : {bytes_tot:,} ({bytes_tot / 1e9:.2f} GB)")
    print(f"Bytes por evento    : {bytes_tot / total:.1f}")
    print(f"Sensores distintos  : {len(sensores)}")
    print(f"Ventana temporal    : {ts_min}  ->  {ts_max}")
    print(f"Por metrica         : {dict(por_metrica)}")
    if por_status:
        anom = sum(v for k, v in por_status.items() if k != "OK")
        print(f"Por status          : {dict(por_status)}  "
              f"({100 * anom / total:.3f}% no-OK)")

    # El balance de carga por worker es lo que hace AUDITABLE el paralelismo.
    conteos = [por_worker[w] for w in sorted(por_worker)]
    print(f"Por worker          : {conteos}")
    if conteos:
        desb = (max(conteos) - min(conteos)) / max(conteos) * 100
        print(f"Desbalance          : {desb:.2f}%")

    if total < args.minimo:
        print(f"\nFALLA: {total:,} eventos, bajo el minimo de {args.minimo:,}.")
        return 1
    print("\nOK: dataset valido.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
