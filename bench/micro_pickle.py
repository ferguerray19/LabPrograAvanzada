"""Micro-benchmark del costo de IPC segun el tamano de lote.

Cubre el punto 5 del informe sin implementar la Opcion A completa: mide
exactamente lo que esa arquitectura habria pagado y nosotros evitamos, con
lotes de 1, 100, 1.000 y 10.000 eventos por `put`.

El experimento esta AISLADO a proposito: no hay fisica, ni disco, ni
formateo. Solo un productor que encola lineas ya serializadas y un consumidor
que las drena. Asi el tiempo medido es atribuible al canal IPC y no a otra
cosa, que es la condicion para poder afirmar algo sobre el en el informe.

    python -m bench.micro_pickle --eventos 1000000 --repeticiones 3

Escribe bench/mediciones_pickle.csv. No inventa nada: los numeros salen de
la maquina donde se ejecuta.
"""

from __future__ import annotations

import argparse
import csv
import multiprocessing as mp
import os
import statistics
import sys
import time
from pathlib import Path

LINEA = (
    '{"timestamp":"2026-08-24T18:40:41.123Z","sensor_id":"REEFER_S3_04",'
    '"metric":"temperature","value":-18.4,"unit":"C","worker_id":3}\n'
)
CENTINELA = "__FIN__"


def productor(cola, n_eventos: int, lote: int) -> None:
    buf = []
    for _ in range(n_eventos):
        buf.append(LINEA)
        if len(buf) >= lote:
            cola.put(buf)          # <- aqui se ENCOLA; el pickle lo hace despues
            buf = []               #    el hilo alimentador oculto (Queue._feed)
    if buf:
        cola.put(buf)
    cola.put(CENTINELA)


def consumidor(cola, n_productores: int, resultado) -> None:
    vivos = n_productores
    total = 0
    while vivos:
        item = cola.get()          # <- aqui SI se paga el unpickle, en linea
        if item == CENTINELA:
            vivos -= 1
            continue
        total += len(item)
    resultado.value = total


def una_corrida(n_eventos: int, lote: int, maxsize: int) -> tuple[float, int]:
    ctx = mp.get_context()
    cola = ctx.Queue(maxsize=maxsize)   # NUNCA ilimitada: sin contrapresion el
    contador = ctx.Value("l", 0)        # delta productor-consumidor crece en RAM
    p = ctx.Process(target=productor, args=(cola, n_eventos, lote))
    c = ctx.Process(target=consumidor, args=(cola, 1, contador))
    t0 = time.perf_counter()
    c.start()
    p.start()
    p.join()
    c.join()
    return time.perf_counter() - t0, contador.value


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Costo de IPC por tamano de lote")
    ap.add_argument("--eventos", type=int, default=1_000_000,
                    help="Trampa N.o 1: ningun experimento por debajo de 1M")
    ap.add_argument("--repeticiones", type=int, default=3)
    ap.add_argument("--lotes", type=int, nargs="+", default=[1, 100, 1_000, 10_000])
    ap.add_argument("--maxsize", type=int, default=64)
    ap.add_argument("--salida", default="bench/mediciones_pickle.csv")
    args = ap.parse_args(argv)

    if args.eventos < 1_000_000:
        print("AVISO: por debajo de 1.000.000 de eventos el ruido del sistema "
              "operativo domina la medicion (Trampa N.o 1).", file=sys.stderr)

    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    filas = []
    print(f"{'lote':>8} {'mediana s':>12} {'ev/s':>14} {'puts':>12}")
    for lote in args.lotes:
        tiempos = []
        for r in range(args.repeticiones + 1):   # +1 de calentamiento, descartada
            t, recibidos = una_corrida(args.eventos, lote, args.maxsize)
            assert recibidos == args.eventos, (recibidos, args.eventos)
            if r > 0:
                tiempos.append(t)
        mediana = statistics.median(tiempos)     # mediana, no la mejor corrida
        puts = -(-args.eventos // lote)
        print(f"{lote:>8} {mediana:>12.3f} {args.eventos / mediana:>14,.0f} {puts:>12,}")
        filas.append({
            "lote": lote, "eventos": args.eventos, "repeticiones": args.repeticiones,
            "maxsize": args.maxsize, "mediana_s": round(mediana, 4),
            "tiempos_s": ";".join(f"{t:.4f}" for t in tiempos),
            "eventos_por_segundo": round(args.eventos / mediana, 1),
            "puts": puts, "python": sys.version.split()[0],
            "nucleos_logicos": os.cpu_count(),
        })

    nuevo = not salida.exists()
    with open(salida, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]))
        if nuevo:
            w.writeheader()
        w.writerows(filas)
    print(f"\nEscrito {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
