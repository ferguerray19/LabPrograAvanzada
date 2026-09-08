"""Cuenta las llamadas REALES a pickle de cada arquitectura.

Responde con un numero la pregunta de defensa «muestrenme en el codigo el
punto exacto donde se paga el costo de pickle». La palabra `pickle` no aparece
en el codigo del simulador: el encurtido lo hace `multiprocessing` por dentro,
en `ForkingPickler.dumps`. Este script parcha esa funcion con un contador
compartido y corre la misma carga con las dos arquitecturas.

    python -m bench.donde_pickle --workers 4 --total-events 200000

Requiere el metodo de arranque `fork`: el parche se aplica en el padre y los
hijos lo heredan. Con `spawn` el hijo levanta un interprete limpio y el parche
no viajaria, que es en si mismo un dato interesante sobre las diferencias
entre metodos de arranque.
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import shutil
import sys
import tempfile
from multiprocessing import reduction
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import arquitectura_a, arquitectura_b, esquema, simulador  # noqa: E402


def instrumentar(contador, bytes_totales):
    """Parcha ForkingPickler.dumps para contar llamadas y bytes.

    Es el unico lugar por el que pasa TODO lo que cruza entre procesos en
    multiprocessing: argumentos de `Process`, tareas de `Pool` y cada `put`
    sobre una `Queue`.
    """
    original = reduction.ForkingPickler.dumps.__func__

    def dumps(cls, obj, protocol=None):
        datos = original(cls, obj, protocol)
        with contador.get_lock():
            contador.value += 1
        with bytes_totales.get_lock():
            bytes_totales.value += len(datos)
        return datos

    reduction.ForkingPickler.dumps = classmethod(dumps)
    return original


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Donde se paga el pickle")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--total-events", type=int, default=200_000)
    ap.add_argument("--batch-size", type=int, default=10_000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--lotes", type=int, nargs="*", default=None,
                    help="si se indica, repite la medicion de --arch queue con "
                         "cada tamano de lote, para ver como se dispara el "
                         "numero de encurtidos sin que cambien los bytes")
    args = ap.parse_args(argv)

    if mp.get_start_method(allow_none=True) not in (None, "fork"):
        print("Este script necesita el metodo 'fork'.", file=sys.stderr)
        return 2

    n_puntos = simulador.contar_puntos(simulador.construir_inventario(args.seed))
    n_ticks = esquema.ticks_necesarios(args.total_events, n_puntos)
    eventos = n_puntos * n_ticks

    contador = mp.Value("l", 0)
    bytes_tot = mp.Value("l", 0)
    instrumentar(contador, bytes_tot)

    tmp = Path(tempfile.mkdtemp(prefix="tpc_pickle_"))
    print(f"carga: {eventos:,} eventos, {args.workers} workers, "
          f"lote {args.batch_size:,}\n")
    print(f"{'arquitectura':>14} {'llamadas a pickle':>19} {'MB encurtidos':>15} "
          f"{'eventos por pickle':>20}")
    try:
        for arch, modulo in (("shard", arquitectura_b), ("queue", arquitectura_a)):
            destino = tmp / arch
            destino.mkdir()
            plan = esquema.PlanCorrida(
                workers=args.workers, total_events=args.total_events,
                output_dir=str(destino), arch=arch, batch_size=args.batch_size,
                seed=args.seed, t0_ms=esquema.parsear_t0("2026-08-24T00:00:00Z"),
                dt_ms=15_000, n_ticks=n_ticks, n_puntos=n_puntos,
                esquema="full", start_method="fork", queue_maxsize=64,
            )
            contador.value = 0
            bytes_tot.value = 0
            modulo.ejecutar(plan)
            n, mb = contador.value, bytes_tot.value / 1e6
            print(f"{arch:>14} {n:>19,} {mb:>15,.1f} "
                  f"{eventos / n:>20,.0f}")
        if args.lotes:
            print(f"\n{'lote (queue)':>14} {'llamadas a pickle':>19} "
                  f"{'MB encurtidos':>15} {'eventos por pickle':>20}")
            for lote in args.lotes:
                destino = tmp / f"lote{lote}"
                destino.mkdir()
                plan = esquema.PlanCorrida(
                    workers=args.workers, total_events=args.total_events,
                    output_dir=str(destino), arch="queue", batch_size=lote,
                    seed=args.seed,
                    t0_ms=esquema.parsear_t0("2026-08-24T00:00:00Z"),
                    dt_ms=15_000, n_ticks=n_ticks, n_puntos=n_puntos,
                    esquema="full", start_method="fork", queue_maxsize=64,
                )
                contador.value = 0
                bytes_tot.value = 0
                arquitectura_a.ejecutar(plan)
                n, mb = contador.value, bytes_tot.value / 1e6
                print(f"{lote:>14,} {n:>19,} {mb:>15,.1f} {eventos / n:>20,.0f}")
            print("\nLos MB encurtidos son los mismos en las cuatro filas: por la")
            print("cola pasa el dataset entero pase lo que pase. Lo que cambia es")
            print("el NUMERO de encurtidos, y con el el costo fijo por llamada:")
            print("recorrer el grafo de punteros, la syscall write, el unpickle.")
            print("Ese costo fijo, multiplicado por millones, es lo que define la")
            print("arquitectura.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nDonde se paga, linea por linea:")
    print("  shard  src/arquitectura_b.py:112  pool.apply_async(...)  -> PlanWorker")
    print("         src/arquitectura_b.py:117  tarea.get()            -> ResumenWorker")
    print("  queue  src/esquema.py:337         self.cola.put(lote)    -> un lote por put")
    print("         src/arquitectura_a.py:158  cola.get(...)          -> el unpickle")
    print("\nOjo con la respuesta facil: put() NO serializa. Encola el objeto en")
    print("un deque interno y retorna; el dumps lo hace despues un hilo")
    print("alimentador oculto (Queue._feed) que escribe al pipe. El unpickle de")
    print("get(), en cambio, si se paga en linea, en el proceso escritor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
