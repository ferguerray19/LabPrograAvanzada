"""Campana experimental de la Fase 1.

Ejecuta el protocolo completo y deja los datos crudos en bench/mediciones.csv.
No produce conclusiones: produce numeros. La interpretacion se escribe en el
informe, a partir de estos datos y no de lo que suele pasar.

Protocolo implementado, punto por punto de la guia:

  * Curva de escalabilidad con 1, 2, 4, 8 y 16 workers, total de eventos fijo.
  * Una corrida de CALENTAMIENTO por configuracion, descartada. La primera
    ejecucion siempre es mas lenta por el cache de paginas del SO.
  * Tres corridas medidas por configuracion; se reporta la MEDIANA, no la
    mejor.
  * Ningun experimento por debajo de 1.000.000 de eventos (Trampa N.o 1).

    python -m bench.campana --total-events 10000000
    python -m bench.campana --hilos-vs-procesos --total-events 2000000

Tiempo de maquina: la campana de escalabilidad son 5 configuraciones x 4
corridas = 20 corridas de 10 millones de eventos cada una. Empezarla el dia
anterior no alcanza.
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import statistics
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))


# ---------------------------------------------------------------------------
# Curva de escalabilidad
# ---------------------------------------------------------------------------


def corrida(workers: int, total: int, salida: Path, etiqueta: str,
            repeticion: int, extra: list[str]) -> float:
    """Lanza el simulador como subproceso y devuelve el tiempo de pared.

    Se invoca por subproceso y no importando `main` para que cada corrida
    parta con un interprete limpio: un modulo ya importado, un cache de
    bytecode caliente o un heap fragmentado contaminarian la comparacion.
    """
    if salida.exists():
        shutil.rmtree(salida)
    cmd = [
        sys.executable, "-m", "src.main",
        "--workers", str(workers),
        "--total-events", str(total),
        "--output-dir", str(salida),
        "--etiqueta", etiqueta,
        "--repeticion", str(repeticion),
        "--log-level", "WARNING",
        "--force",
        *extra,
    ]
    t0 = time.perf_counter()
    r = subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True)
    dt = time.perf_counter() - t0
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        raise SystemExit(f"la corrida con {workers} workers fallo")
    return dt


def escalabilidad(args) -> None:
    salida = Path(args.output_dir)
    resumen = []
    print(f"{'workers':>8} {'mediana s':>11} {'speedup':>9} {'eficiencia':>11} "
          f"{'ev/s':>12}")
    base = None
    for w in args.workers:
        tiempos = []
        for i in range(args.repeticiones + 1):
            # i = 0 es el calentamiento. Va al CSV igual, marcado como tal:
            # descartarlo del analisis no es lo mismo que no registrarlo, y
            # la guia pide dejar dicho que se hizo.
            t = corrida(w, args.total_events, salida, args.etiqueta, i,
                        ["--batch-size", str(args.batch_size)] + args.extra)
            if i > 0:
                tiempos.append(t)
        m = statistics.median(tiempos)
        if base is None:
            base = m
        s = base / m
        print(f"{w:>8} {m:>11.2f} {s:>9.2f} {s / w:>11.2f} "
              f"{args.total_events / m:>12,.0f}")
        resumen.append({
            "workers": w, "mediana_s": round(m, 3),
            "tiempos_s": ";".join(f"{t:.3f}" for t in tiempos),
            "speedup": round(s, 4), "eficiencia": round(s / w, 4),
            "eventos_por_segundo": round(args.total_events / m, 1),
            "total_eventos": args.total_events, "etiqueta": args.etiqueta,
        })

    ruta = Path("bench/escalabilidad.csv")
    nuevo = not ruta.exists()
    with open(ruta, "a", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(resumen[0]))
        if nuevo:
            wr.writeheader()
        wr.writerows(resumen)
    print(f"\nEscrito {ruta}. Los datos crudos por corrida estan en "
          f"bench/mediciones.csv (una fila por ejecucion del simulador).")


def _serie(args, etiqueta: str, banderas: list[str], titulo: str) -> list[float]:
    """Una configuracion: un calentamiento descartado y N medidas.

    Devuelve los tiempos MEDIDOS. La corrida de calentamiento se ejecuta y se
    registra en el CSV marcada como tal -la guia pide dejarlo dicho- pero no
    entra en la mediana: la primera ejecucion siempre es mas lenta por el
    cache de paginas del sistema operativo.
    """
    salida = Path(args.output_dir)
    tiempos = []
    for i in range(args.repeticiones + 1):
        t = corrida(args.workers_fijo, args.total_events, salida, etiqueta, i,
                    banderas + args.extra)
        if i > 0:
            tiempos.append(t)
    m = statistics.median(tiempos)
    print(f"{titulo:>22} {m:>11.2f} {args.total_events / m:>14,.0f}")
    return tiempos


def barrido_arquitectura(args) -> None:
    """Opcion A contra Opcion B con el mismo numero de trabajadores.

    Es LA comparacion arquitectonica: mismo bucle de generacion, misma carga,
    mismo reparto de activos; lo unico que cambia es como llegan los eventos
    al disco. Cualquier diferencia es atribuible al patron de escritura.

    Advertencia al interpretar: la Opcion A produce UN archivo y la B produce
    N. En SSD NVMe se espera que B aproveche mejor el ancho de banda; en disco
    mecanico puede ser al reves, porque varios flujos simultaneos obligan al
    cabezal a saltar. Si trabajan sobre HDD, eso es un hallazgo del informe,
    no un error.
    """
    print(f"carga fija: {args.total_events:,} eventos, "
          f"{args.workers_fijo} workers, batch {args.batch_size}\n")
    print(f"{'configuracion':>22} {'mediana s':>11} {'ev/s':>14}")
    filas = []
    for arch in args.archs:
        banderas = ["--arch", arch, "--batch-size", str(args.batch_size)]
        if arch == "queue":
            banderas += ["--queue-maxsize", str(args.queue_maxsize)]
        t = _serie(args, f"{args.etiqueta}-arch", banderas, arch)
        filas.append({
            "experimento": "arquitectura", "arch": arch,
            "workers": args.workers_fijo, "batch_size": args.batch_size,
            "queue_maxsize": args.queue_maxsize if arch == "queue" else "",
            "mediana_s": round(statistics.median(t), 3),
            "tiempos_s": ";".join(f"{x:.3f}" for x in t),
            "eventos_por_segundo": round(args.total_events / statistics.median(t), 1),
            "total_eventos": args.total_events,
        })
    _volcar(Path("bench/comparacion_arquitecturas.csv"), filas)


def barrido_lotes(args) -> None:
    """Punto 5 de la seccion 4.4: costo de pickle segun eventos por put.

    A diferencia de `bench/micro_pickle.py`, que aisla el canal IPC sin fisica
    ni disco, esto mide el simulador COMPLETO con --arch queue. Los dos son
    complementarios: el micro-benchmark acota el costo puro de la
    serializacion, y este muestra cuanto de ese costo se ve en el tiempo total
    cuando compite con la generacion y la escritura.

    Con --batch-size 1 se paga un pickle, un write al pipe y un unpickle por
    CADA evento. Considere reducir --total-events para esta serie si la
    corrida con lote 1 se hace impracticable, pero no baje de un millon
    (Trampa N.o 1).
    """
    print(f"carga fija: {args.total_events:,} eventos, "
          f"{args.workers_fijo} workers, --arch queue\n")
    print(f"{'configuracion':>22} {'mediana s':>11} {'ev/s':>14}")
    filas = []
    for lote in args.lotes:
        banderas = ["--arch", "queue", "--batch-size", str(lote),
                    "--queue-maxsize", str(args.queue_maxsize)]
        t = _serie(args, f"{args.etiqueta}-lotes", banderas, f"lote={lote}")
        mediana = statistics.median(t)
        filas.append({
            "experimento": "lotes", "arch": "queue",
            "workers": args.workers_fijo, "batch_size": lote,
            "queue_maxsize": args.queue_maxsize,
            "mediana_s": round(mediana, 3),
            "tiempos_s": ";".join(f"{x:.3f}" for x in t),
            "eventos_por_segundo": round(args.total_events / mediana, 1),
            "total_eventos": args.total_events,
            # puts totales: es la magnitud que explica la curva
            "puts_aproximados": -(-args.total_events // lote),
        })
    _volcar(Path("bench/comparacion_lotes.csv"), filas)


def _volcar(ruta: Path, filas: list[dict]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    nuevo = not ruta.exists()
    with open(ruta, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]))
        if nuevo:
            w.writeheader()
        w.writerows(filas)
    print(f"\nEscrito {ruta}. Las filas crudas de cada corrida, incluidas las "
          f"de calentamiento, estan en bench/mediciones.csv.")


# ---------------------------------------------------------------------------
# Hilos contra procesos
# ---------------------------------------------------------------------------


def _tarea_generar(argumentos):
    """Trabajo CPU-bound identico al del simulador: fisica, construccion del
    evento y serializacion. Todo bytecode puro, ninguna syscall bloqueante,
    asi que el GIL no se libera nunca."""
    from src import esquema, simulador
    wid, indices, n_ticks, seed = argumentos
    todos = simulador.construir_inventario(seed)
    activos = [todos[i] for i in indices]
    plan = esquema.PlanWorker(
        worker_id=wid, indices_activos=tuple(indices),
        t0_ms=esquema.parsear_t0("2026-08-24T00:00:00Z"), dt_ms=15_000,
        n_ticks=n_ticks, seed=seed, batch_size=10_000,
        output_dir=".", esquema="full",
    )
    return esquema.bucle_worker(plan, activos, esquema.SumideroNulo())


def hilos_vs_procesos(args) -> None:
    """El experimento de diez minutos que la guia describe como el mejor
    argumento de la defensa.

    Se escribe a `SumideroNulo` a proposito: al eliminar el disco de la
    ecuacion, cualquier diferencia entre hilos y procesos es atribuible al
    GIL y no al almacenamiento. Es esperable que la version con 4 hilos
    resulte ALGO MAS LENTA que la secuencial, por el costo de los cambios de
    contexto y la contencion por el propio candado.
    """
    from src import simulador
    activos = simulador.construir_inventario(args.seed)
    puntos = simulador.contar_puntos(activos)
    n_ticks = -(-args.total_events // puntos)
    print(f"carga: {puntos} puntos x {n_ticks} ticks = {puntos * n_ticks:,} eventos\n")
    print(f"{'modo':>12} {'n':>4} {'mediana s':>11} {'speedup':>9}")

    filas = []
    base_sec = None
    for modo in ("secuencial", "hilos", "procesos"):
        for n in ([1] if modo == "secuencial" else args.workers):
            cubos = simulador.asignar_workers(activos, n)
            tareas = [(i, list(c), n_ticks, args.seed) for i, c in enumerate(cubos)]
            tiempos = []
            for rep in range(args.repeticiones + 1):
                t0 = time.perf_counter()
                if modo == "secuencial":
                    for t in tareas:
                        _tarea_generar(t)
                elif modo == "hilos":
                    with ThreadPoolExecutor(max_workers=n) as ex:
                        list(ex.map(_tarea_generar, tareas))
                else:
                    with ProcessPoolExecutor(max_workers=n) as ex:
                        list(ex.map(_tarea_generar, tareas))
                dt = time.perf_counter() - t0
                if rep > 0:
                    tiempos.append(dt)
            m = statistics.median(tiempos)
            if base_sec is None:
                base_sec = m
            print(f"{modo:>12} {n:>4} {m:>11.2f} {base_sec / m:>9.2f}")
            filas.append({
                "modo": modo, "n": n, "mediana_s": round(m, 3),
                "tiempos_s": ";".join(f"{t:.3f}" for t in tiempos),
                "speedup_vs_secuencial": round(base_sec / m, 4),
                "eventos": puntos * n_ticks,
                "nucleos_logicos": os.cpu_count(),
            })

    ruta = Path("bench/hilos_vs_procesos.csv")
    nuevo = not ruta.exists()
    with open(ruta, "a", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(filas[0]))
        if nuevo:
            wr.writeheader()
        wr.writerows(filas)
    print(f"\nEscrito {ruta}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Campana experimental Fase 1")
    ap.add_argument("--total-events", type=int, default=10_000_000)
    ap.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4, 8, 16])
    ap.add_argument("--repeticiones", type=int, default=3)
    ap.add_argument("--output-dir", default="data/bench_tmp")
    ap.add_argument("--etiqueta", default="escalabilidad")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--barrido", choices=("escalabilidad", "arquitectura",
                                          "lotes", "hilos"),
                    default="escalabilidad",
                    help="que experimento correr")
    ap.add_argument("--workers-fijo", type=int, default=8,
                    help="numero de workers de los barridos que NO varian "
                         "workers (arquitectura y lotes)")
    ap.add_argument("--archs", nargs="+", default=["shard", "queue"],
                    help="arquitecturas a comparar en el barrido 'arquitectura'")
    ap.add_argument("--lotes", type=int, nargs="+",
                    default=[1, 100, 1_000, 10_000],
                    help="tamanos de lote del barrido 'lotes'")
    ap.add_argument("--batch-size", type=int, default=10_000,
                    help="lote fijo del barrido 'arquitectura'")
    ap.add_argument("--queue-maxsize", type=int, default=64)
    ap.add_argument("--hilos-vs-procesos", action="store_true",
                    help="alias de --barrido hilos")
    ap.add_argument("--extra", nargs=argparse.REMAINDER, default=[],
                    help="argumentos extra que se pasan tal cual a src.main")
    args = ap.parse_args(argv)

    if args.total_events < 1_000_000:
        print("Trampa N.o 1: ningun experimento se valida con menos de un "
              "millon de eventos.", file=sys.stderr)
        return 2

    if args.hilos_vs_procesos:
        args.barrido = "hilos"
    {
        "escalabilidad": escalabilidad,
        "arquitectura": barrido_arquitectura,
        "lotes": barrido_lotes,
        "hilos": hilos_vs_procesos,
    }[args.barrido](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
