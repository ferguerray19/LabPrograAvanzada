"""Punto de entrada del simulador TPC Sitio 3.

Responsabilidades de este modulo, y solo estas:
  1. Parsear y VALIDAR los argumentos de linea de comandos.
  2. Construir el `PlanCorrida` inmutable.
  3. Configurar el metodo de arranque de procesos y el logging multiproceso.
  4. Despachar a la arquitectura elegida.
  5. Escribir el manifiesto y la fila de `bench/mediciones.csv`.

No contiene fisica, ni serializacion, ni conocimiento de como se escribe el
dataset. Eso vive en `simulador.py`, `esquema.py` y `arquitectura_*.py`.

Uso tipico:

    python -m src.main --workers 8 --total-events 10000000 \\
        --output-dir data/raw --arch shard --batch-size 10000 \\
        --seed 42 --sim-days 9
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import logging.handlers
import multiprocessing as mp
import os
import platform
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import resource  # POSIX unicamente
except ImportError:  # Windows
    resource = None

from . import arquitectura_a, arquitectura_b, esquema, simulador
from .esquema import PlanCorrida

MINIMO_DURO = 10_000_000

#: Estimacion conservadora de bytes por evento, usada solo para avisar de
#: falta de espacio ANTES de empezar a escribir. El valor real lo reporta el
#: manifiesto al terminar.
BYTES_POR_EVENTO = {"min": 170, "full": 215}

log = logging.getLogger("tpc")


# ---------------------------------------------------------------------------
# Instrumentacion de memoria (punto 6 de la seccion 4.4)
# ---------------------------------------------------------------------------


def _factor_maxrss_a_mb() -> float:
    """Factor de conversion de `ru_maxrss` a megabytes.

    La unidad de `ru_maxrss` NO esta estandarizada y esto es una fuente
    clasica de informes con cifras mil veces equivocadas:

      * Linux  (getrusage(2)): kilobytes.
      * macOS  (BSD):          bytes.
      * Solaris/AIX:           paginas. No se soportan aqui; se asume KB.

    Se resuelve mirando `sys.platform` explicitamente y no adivinando por el
    orden de magnitud del valor, que a veces coincide y a veces no.
    """
    return 1 / 1024 if sys.platform != "darwin" else 1 / (1024 * 1024)


def pico_memoria_mb() -> tuple[float | None, float | None]:
    """Pico de RSS del proceso padre y de sus hijos, en MB.

    Devuelve (None, None) si `resource` no existe -Windows-, para que la
    corrida no se caiga por no poder medir. La ausencia de medicion se
    registra como celda vacia en el CSV, que es informacion honesta.

    Tres advertencias que conviene conocer antes de citar estos numeros:

      * RUSAGE_CHILDREN devuelve el maximo de UN hijo, no la suma de todos.
        Es el pico individual mas alto observado, que es justamente lo que
        importa para saber si un proceso se acerco al limite de RAM.
      * Solo cuenta hijos ya recolectados (`wait`). Por eso se mide DESPUES
        de que `ejecutar` retorna, con el pool cerrado y los procesos unidos.
      * Es acumulativo durante toda la vida del proceso padre y no se puede
        reiniciar. En una corrida por invocacion, como aqui, no molesta; si
        se llamara a `ejecutar` varias veces en el mismo interprete, el valor
        seria el maximo historico y no el de la ultima corrida.

    `tracemalloc` no sirve para esto: mide asignaciones del heap de Python
    dentro del proceso que lo activa, y no ve la memoria de los hijos ni los
    buffers del propio interprete.
    """
    if resource is None:
        return None, None
    f = _factor_maxrss_a_mb()
    propio = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * f
    hijos = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * f
    return round(propio, 2), round(hijos, 2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m src.main",
        description="Generador de logs crudos masivos - TPC Sitio 3, Fase 1.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--workers", type=int, default=os.cpu_count() or 4,
                   help="numero de procesos trabajadores")
    p.add_argument("--total-events", type=int, default=MINIMO_DURO,
                   help="piso de eventos a generar; el total real lo redondea "
                        "hacia arriba al tick completo mas cercano")
    p.add_argument("--output-dir", type=str, default="data/raw",
                   help="carpeta de salida de los .jsonl")
    p.add_argument("--arch", choices=("shard", "queue"), default="shard",
                   help="shard = archivos segmentados (Opcion B); "
                        "queue = escritor unico (Opcion A, no implementada)")
    p.add_argument("--batch-size", type=int, default=10_000,
                   help="eventos por lote: lineas acumuladas antes de cada "
                        "writelines (shard) o de cada put (queue)")
    p.add_argument("--queue-maxsize", type=int, default=64,
                   help="solo con --arch queue: mensajes maximos en la cola. "
                        "Acota la RAM en ~maxsize x batch-size eventos y es "
                        "lo que produce la contrapresion. Nunca ilimitada")
    p.add_argument("--seed", type=int, default=42,
                   help="semilla maestra; misma semilla = mismo dataset")
    p.add_argument("--sim-days", type=float, default=None,
                   help="si se indica, la ventana simulada manda sobre "
                        "--total-events y el total se deriva de ella")
    p.add_argument("--start-time", type=str, default="2026-08-24T00:00:00Z",
                   help="instante inicial de la simulacion, ISO 8601 UTC. "
                        "Constante por defecto para no romper la "
                        "reproducibilidad; nunca es el reloj del sistema")
    p.add_argument("--interval-s", type=float, default=15.0,
                   help="periodo de muestreo de los sensores, en segundos")
    p.add_argument("--esquema", choices=("min", "full"), default="full",
                   help="min = los 6 campos obligatorios; "
                        "full = ademas site, asset_type, status y seq")
    p.add_argument("--start-method", choices=("fork", "spawn", "forkserver"),
                   default=None, help="metodo de arranque de multiprocessing; "
                        "por defecto el del sistema")
    p.add_argument("--bench-csv", type=str, default="bench/mediciones.csv",
                   help="CSV al que se anexa una fila por corrida")
    p.add_argument("--etiqueta", type=str, default="",
                   help="nombre del experimento; agrupa corridas en el CSV")
    p.add_argument("--repeticion", type=int, default=1,
                   help="numero de repeticion dentro del experimento. "
                        "0 marca la corrida de calentamiento, que se descarta "
                        "al calcular la mediana")
    p.add_argument("--force", action="store_true",
                   help="sobrescribe una carpeta de salida que ya tenga shards")
    p.add_argument("--log-level", default="INFO",
                   choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    return p


def validar(args: argparse.Namespace) -> None:
    """Falla temprano y con mensaje claro.

    Criterio para separar error fatal de advertencia: es FATAL lo que
    garantiza una corrida invalida o un cuelgue, y es ADVERTENCIA lo que
    solo produce un resultado subóptimo pero legitimo. Pedir `--workers 200`
    en un equipo de 8 nucleos entra en la segunda categoria hasta cierto
    punto -oversubscription es un experimento valido y la guia pide medir
    hasta 16 workers-, pero pasado un limite es una bomba de procesos.
    """
    nucleos = os.cpu_count() or 1
    fatales: list[str] = []

    if args.workers < 1:
        fatales.append("--workers debe ser >= 1")
    elif args.workers > 8 * nucleos:
        fatales.append(
            f"--workers {args.workers} con {nucleos} nucleos logicos: mas de 8x "
            "el paralelismo disponible. Se rechaza para no bloquear el equipo."
        )
    elif args.workers > nucleos:
        log.warning(
            "--workers %d supera los %d nucleos logicos: habra oversubscription "
            "y se espera que el tiempo total empeore. Es una corrida valida "
            "para la curva de escalabilidad, pero no para la corrida final.",
            args.workers, nucleos,
        )

    if args.total_events < 1:
        fatales.append("--total-events debe ser >= 1")
    elif args.total_events < MINIMO_DURO and args.sim_days is None:
        log.warning(
            "--total-events %d esta bajo el minimo de %d exigido por la guia. "
            "Sirve para pruebas, NO para la entrega.",
            args.total_events, MINIMO_DURO,
        )

    if args.batch_size < 1:
        fatales.append("--batch-size debe ser >= 1")
    elif args.batch_size > 5_000_000:
        log.warning("--batch-size %d retiene mucha memoria por worker antes de "
                    "cada volcado", args.batch_size)

    if args.queue_maxsize < 1:
        # Una cola ilimitada (maxsize<=0 en la API de multiprocessing) elimina
        # la contrapresion: los productores corren a velocidad de CPU, el
        # escritor a velocidad de disco, y la diferencia se acumula en RAM
        # hasta que el kernel mata el proceso. Se rechaza explicitamente.
        fatales.append(
            "--queue-maxsize debe ser >= 1. Una cola ilimitada elimina la "
            "contrapresion y termina en OOM (guia, seccion 2.2)."
        )
    if args.interval_s <= 0:
        fatales.append("--interval-s debe ser > 0")
    if args.sim_days is not None and args.sim_days <= 0:
        fatales.append("--sim-days debe ser > 0")

    try:
        esquema.parsear_t0(args.start_time)
    except ValueError as exc:
        fatales.append(str(exc))

    salida = Path(args.output_dir)
    existentes = sorted(salida.glob("*.jsonl")) if salida.is_dir() else []
    if existentes and not args.force:
        fatales.append(
            f"{salida} ya contiene {len(existentes)} archivo(s) .jsonl. "
            "Mezclarlos con una corrida nueva produciria un dataset "
            "inconsistente. Borrelos o use --force."
        )

    if fatales:
        for m in fatales:
            log.error(m)
        raise SystemExit(2)


def verificar_espacio(args: argparse.Namespace, eventos: int) -> None:
    """Comprueba el disco ANTES de escribir. Quedarse sin espacio a los ocho
    minutos de corrida deja un shard truncado y valido, que es el peor de los
    fallos posibles de la Opcion B porque es silencioso."""
    necesarios = eventos * BYTES_POR_EVENTO[args.esquema]
    destino = Path(args.output_dir)
    destino.mkdir(parents=True, exist_ok=True)
    libres = shutil.disk_usage(destino).free
    if libres < necesarios * 1.1:
        log.error(
            "espacio insuficiente en %s: se estiman %.2f GB y hay %.2f GB libres",
            destino, necesarios / 1e9, libres / 1e9,
        )
        raise SystemExit(2)
    log.info("estimacion de salida: %.2f GB (%.2f GB libres)",
             necesarios / 1e9, libres / 1e9)


# ---------------------------------------------------------------------------
# Logging multiproceso
# ---------------------------------------------------------------------------


def _init_worker_logging(cola, nivel: int) -> None:
    """Inicializador de cada proceso hijo del Pool.

    Un `FileHandler` abierto por el padre y heredado por N hijos reproduce
    exactamente el problema de corrupcion de la seccion 2.1 de la guia: cada
    hijo tiene su propio buffer de usuario y los vuelca cuando se llenan, no
    en los limites de linea. La diferencia es que aqui el desastre queda
    escondido detras de una API que parece confiable.

    El patron correcto: los hijos solo ENCOLAN registros (`QueueHandler`), y
    un unico hilo del padre (`QueueListener`) es el que escribe. Es el mismo
    principio de la Opcion A, aplicado al log operativo en vez de a los datos.
    """
    raiz = logging.getLogger()
    raiz.handlers[:] = [logging.handlers.QueueHandler(cola)]
    raiz.setLevel(nivel)


def configurar_logging(nivel: str):
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(processName)s] %(name)s: %(message)s"
    )
    consola = logging.StreamHandler(sys.stderr)
    consola.setFormatter(fmt)
    raiz = logging.getLogger()
    raiz.handlers[:] = [consola]
    raiz.setLevel(getattr(logging, nivel))
    return consola


# ---------------------------------------------------------------------------
# Salidas de metadatos
# ---------------------------------------------------------------------------


def escribir_manifiesto(plan: PlanCorrida, resumen, args, ruta: Path,
                        mem_padre=None, mem_hijos=None) -> dict:
    """El manifiesto es lo que permite verificar que no se perdio nada y lo
    que alimenta el informe. Registra dos tiempos distintos que es facil
    confundir: `ejecutado_utc` es cuando corrio el programa, `sim_inicio` es
    el instante simulado del dataset."""
    ahora = datetime.now(timezone.utc)
    manifiesto = {
        # identificador unico y legible de la corrida: enlaza esta fila del
        # CSV con el manifiesto que quedo junto al dataset
        "corrida_id": (
            f"{ahora.strftime('%Y%m%dT%H%M%S')}-{plan.arch}-w{plan.workers}"
            f"-r{args.repeticion}"
        ),
        "ejecutado_utc": ahora.isoformat(timespec="seconds"),
        "duracion_s": round(resumen.duracion_s, 3),
        "total_eventos": resumen.eventos,
        "total_bytes": resumen.bytes,
        "bytes_por_evento": round(resumen.bytes / resumen.eventos, 2),
        "eventos_por_segundo": round(resumen.eventos / resumen.duracion_s, 1),
        "mb_por_segundo": round(resumen.bytes / 1e6 / resumen.duracion_s, 2),
        "archivos": resumen.archivos,
        "arquitectura": plan.arch,
        "workers": plan.workers,
        "seed": plan.seed,
        "esquema": plan.esquema,
        "batch_size": plan.batch_size,
        "sim_inicio": args.start_time,
        "sim_intervalo_s": args.interval_s,
        "sim_ticks": plan.n_ticks,
        "sim_dias": round(plan.sim_days, 4),
        "puntos_de_medicion": plan.n_puntos,
        "start_method": plan.start_method,
        "queue_maxsize": plan.queue_maxsize if plan.arch == "queue" else None,
        "memoria": {
            # None si el sistema no expone getrusage (Windows). La unidad
            # nativa de ru_maxrss depende del sistema; ya viene normalizada.
            "pico_padre_mb": mem_padre,
            "pico_hijo_mayor_mb": mem_hijos,
            "medido_con": "resource.getrusage" if resource else "no disponible",
            "nota": ("RUSAGE_CHILDREN entrega el pico del hijo mas grande, "
                     "no la suma de los hijos"),
        },
        "entorno": {
            "python": platform.python_version(),
            "implementacion": platform.python_implementation(),
            "so": f"{platform.system()} {platform.release()}",
            "maquina": platform.machine(),
            "nucleos_logicos": os.cpu_count(),
        },
        "detalles": [
            {
                "worker_id": r.worker_id,
                "archivo": r.archivo,
                "eventos": r.eventos,
                "bytes": r.bytes,
                "puntos": r.puntos,
                "duracion_s": round(r.duracion_s, 3),
            }
            for r in resumen.detalles
        ],
    }
    ruta.write_text(json.dumps(manifiesto, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifiesto


#: Columnas de bench/mediciones.csv, agrupadas por naturaleza y en orden fijo:
#: identidad de la corrida, configuracion, resultados, entorno. El orden es
#: parte del contrato: los scripts de bench/ y las tablas del informe lo
#: asumen, y un CSV cuyas columnas cambian de posicion entre corridas no
#: sirve como evidencia.
COLUMNAS_CSV = (
    # --- identidad -------------------------------------------------------
    "corrida_id", "etiqueta", "fase", "repeticion", "ejecutado_utc",
    # --- configuracion ---------------------------------------------------
    "arch", "workers", "batch_size", "queue_maxsize", "esquema", "seed",
    "start_method",
    "intervalo_s", "sim_ticks", "sim_dias", "puntos",
    # --- resultados ------------------------------------------------------
    "duracion_s", "total_eventos", "total_bytes", "eventos_por_segundo",
    "mb_por_segundo", "bytes_por_evento", "worker_min_s", "worker_max_s",
    "desbalance_puntos", "pico_padre_mb", "pico_hijo_mayor_mb",
    # --- entorno ---------------------------------------------------------
    "python", "so", "maquina", "nucleos_logicos",
)

#: Clave de ordenamiento. Deja juntas todas las corridas de una misma
#: configuracion, con su calentamiento (repeticion 0) primero.
_ORDEN = ("etiqueta", "arch", "esquema", "workers", "repeticion", "ejecutado_utc")


def _clave_orden(fila: dict):
    def num(v):
        try:
            return (0, float(v))
        except (TypeError, ValueError):
            return (1, 0.0)

    return (
        str(fila.get("etiqueta", "")),
        str(fila.get("arch", "")),
        str(fila.get("esquema", "")),
        num(fila.get("workers")),
        num(fila.get("repeticion")),
        str(fila.get("ejecutado_utc", "")),
    )


def anexar_csv(ruta: Path, manifiesto: dict, args) -> None:
    """Agrega la fila de esta corrida y reescribe el archivo ORDENADO.

    Trampa N.o 8: la evidencia del informe son datos tabulados, no capturas
    del terminal. El simulador emite su propia fila al terminar cada corrida
    y los graficos se construyen desde aqui.

    El archivo se reescribe entero en cada corrida en vez de solo anexar.
    Cuesta milisegundos sobre unas pocas decenas de filas y compra tres cosas
    que un `append` ciego no da: las corridas de una misma configuracion
    quedan contiguas y en orden de repeticion, el orden de columnas es
    siempre el mismo, y un CSV escrito por una version anterior del programa
    se migra al vuelo rellenando las columnas que falten en lugar de quedar
    desalineado.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)

    previas: list[dict] = []
    if ruta.exists():
        with open(ruta, encoding="utf-8", newline="") as f:
            for fila in csv.DictReader(f):
                previas.append({c: fila.get(c, "") for c in COLUMNAS_CSV})

    dur = [d["duracion_s"] for d in manifiesto["detalles"]]
    pts = [d["puntos"] for d in manifiesto["detalles"]]
    ent = manifiesto["entorno"]
    nueva = {
        "corrida_id": manifiesto["corrida_id"],
        "etiqueta": args.etiqueta,
        # `fase` se deriva de la repeticion en vez de ser un flag aparte: la
        # corrida 0 es siempre la de calentamiento, que se descarta porque la
        # primera ejecucion es mas lenta por el cache de paginas del SO.
        "fase": "calentamiento" if args.repeticion == 0 else "medida",
        "repeticion": args.repeticion,
        "ejecutado_utc": manifiesto["ejecutado_utc"],
        "arch": manifiesto["arquitectura"],
        "workers": manifiesto["workers"],
        "batch_size": manifiesto["batch_size"],
        "esquema": manifiesto["esquema"],
        "seed": manifiesto["seed"],
        "queue_maxsize": manifiesto["queue_maxsize"] or "",
        "start_method": manifiesto["start_method"],
        "intervalo_s": manifiesto["sim_intervalo_s"],
        "sim_ticks": manifiesto["sim_ticks"],
        "sim_dias": manifiesto["sim_dias"],
        "puntos": manifiesto["puntos_de_medicion"],
        "duracion_s": manifiesto["duracion_s"],
        "total_eventos": manifiesto["total_eventos"],
        "total_bytes": manifiesto["total_bytes"],
        "eventos_por_segundo": manifiesto["eventos_por_segundo"],
        "mb_por_segundo": manifiesto["mb_por_segundo"],
        "bytes_por_evento": manifiesto["bytes_por_evento"],
        "worker_min_s": round(min(dur), 3),
        "worker_max_s": round(max(dur), 3),
        "desbalance_puntos": max(pts) - min(pts),
        "pico_padre_mb": manifiesto["memoria"]["pico_padre_mb"] if
            manifiesto["memoria"]["pico_padre_mb"] is not None else "",
        "pico_hijo_mayor_mb": manifiesto["memoria"]["pico_hijo_mayor_mb"] if
            manifiesto["memoria"]["pico_hijo_mayor_mb"] is not None else "",
        "python": ent["python"],
        "so": ent["so"],
        "maquina": ent["maquina"],
        "nucleos_logicos": ent["nucleos_logicos"],
    }

    filas = sorted([*previas, nueva], key=_clave_orden)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS_CSV)
        w.writeheader()
        w.writerows(filas)
    # reemplazo atomico: si el proceso muere a mitad de la reescritura, el
    # CSV anterior sigue intacto en vez de quedar truncado
    tmp.replace(ruta)


# ---------------------------------------------------------------------------
# Orquestacion
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    configurar_logging(args.log_level)
    validar(args)

    # El inventario define cuantos puntos reportan por tick, y de ahi sale
    # cuantos ticks hacen falta. Es el punto donde el minimo de 10 millones se
    # interpreta como PISO: se redondea hacia arriba para que los ~180 puntos
    # cubran todos exactamente la misma ventana temporal.
    activos = simulador.construir_inventario(args.seed)
    n_puntos = simulador.contar_puntos(activos)
    dt_ms = int(round(args.interval_s * 1000))

    if args.sim_days is not None:
        n_ticks = max(1, int(args.sim_days * 86_400_000 // dt_ms))
        if n_ticks * n_puntos < MINIMO_DURO:
            log.warning(
                "--sim-days %.2f produce %d eventos, bajo el minimo de %d",
                args.sim_days, n_ticks * n_puntos, MINIMO_DURO,
            )
    else:
        n_ticks = esquema.ticks_necesarios(args.total_events, n_puntos)

    plan = PlanCorrida(
        workers=args.workers,
        total_events=args.total_events,
        output_dir=args.output_dir,
        arch=args.arch,
        batch_size=args.batch_size,
        seed=args.seed,
        t0_ms=esquema.parsear_t0(args.start_time),
        dt_ms=dt_ms,
        n_ticks=n_ticks,
        n_puntos=n_puntos,
        esquema=args.esquema,
        start_method=args.start_method or mp.get_start_method(),
        queue_maxsize=args.queue_maxsize,
    )

    verificar_espacio(args, plan.eventos_esperados)
    log.info(
        "plan: %d workers, %d puntos x %d ticks = %d eventos (%.2f dias simulados)",
        plan.workers, plan.n_puntos, plan.n_ticks, plan.eventos_esperados,
        plan.sim_days,
    )

    if args.start_method:
        ctx = mp.get_context(args.start_method)
    else:
        ctx = mp.get_context()

    # Log operativo de los hijos por QueueHandler/QueueListener.
    cola_log = ctx.Queue(-1)
    listener = logging.handlers.QueueListener(
        cola_log, *logging.getLogger().handlers, respect_handler_level=True
    )
    listener.start()

    modulo = arquitectura_b if args.arch == "shard" else arquitectura_a
    t_pared = time.perf_counter()
    try:
        resumen = modulo.ejecutar(
            plan, ctx=ctx,
            initializer=_init_worker_logging,
            initargs=(cola_log, getattr(logging, args.log_level)),
        )
    except NotImplementedError as exc:
        log.error("%s", exc)
        return 2
    except Exception:
        log.exception("la corrida fallo; el dataset en %s NO es valido",
                      args.output_dir)
        return 1
    finally:
        listener.stop()

    # Se mide DESPUES de que `ejecutar` retorno: en ese punto los hijos ya
    # fueron recolectados y RUSAGE_CHILDREN tiene datos.
    mem_padre, mem_hijos = pico_memoria_mb()

    salida = Path(args.output_dir)
    manifiesto = escribir_manifiesto(plan, resumen, args,
                                     salida / "manifiesto.json",
                                     mem_padre, mem_hijos)
    anexar_csv(Path(args.bench_csv), manifiesto, args)

    log.info(
        "OK: %d eventos, %.2f GB, %.2f s (%.0f ev/s, %.1f MB/s). Total de pared %.2f s.",
        resumen.eventos, resumen.bytes / 1e9, resumen.duracion_s,
        manifiesto["eventos_por_segundo"], manifiesto["mb_por_segundo"],
        time.perf_counter() - t_pared,
    )
    return 0


# La guarda no es una formalidad (Trampa N.o 3). Con `spawn` -el metodo por
# defecto en Windows y en macOS moderno- cada proceso hijo REIMPORTA este
# modulo completo para poder resolver `trabajador_shard` por nombre. Sin la
# guarda, ese reimport volveria a ejecutar `main()`, cada hijo crearia su
# propio Pool, y esos nietos harian lo mismo: una bomba de procesos que
# congela el equipo. Con la guarda, el hijo importa el modulo, `__name__` vale
# "src.main" y no "__main__", y el bloque no se ejecuta.
if __name__ == "__main__":
    raise SystemExit(main())
