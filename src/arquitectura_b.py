"""Opcion B: archivos segmentados, un .jsonl por proceso trabajador.

Por que esta arquitectura y no la Opcion A (proceso escritor unico):

  * No hay recurso compartido, asi que no hay nada que sincronizar. El
    antipatron de la seccion 2.1 de la guia -varios procesos escribiendo el
    mismo descriptor y cortandose las lineas entre si- es imposible aqui por
    construccion, no por disciplina.
  * El unico `pickle` de toda la corrida es el del `PlanWorker` al arrancar
    cada hijo y el del `ResumenWorker` al volver. Con 8 workers son 16
    encurtidos, contra ~2.000 por cada millon de eventos en la Opcion A.
  * El sistema operativo planifica las escrituras de N descriptores como le
    convenga y aprovecha el ancho de banda completo del disco.

Su modo de falla propio, y es SILENCIOSO: si un worker muere a mitad, su
archivo queda truncado pero perfectamente valido. Todas las lineas parsean,
el validador dice OK, y el dataset tiene menos registros de los exigidos. La
defensa contra eso es el control de conteo en `ejecutar`, no la buena suerte.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import time
from pathlib import Path

from . import esquema, simulador
from .esquema import PlanCorrida, PlanWorker, ResumenCorrida, ResumenWorker

log = logging.getLogger(__name__)


def trabajador_shard(plan: PlanWorker) -> ResumenWorker:
    """Cuerpo del proceso hijo. Debe ser una funcion de modulo de nivel
    superior: con el metodo de arranque `spawn` el hijo reimporta el modulo y
    busca la funcion por nombre, asi que una funcion anidada o definida en una
    celda de notebook no seria recuperable.

    Solo devuelve estadisticas. Ningun evento cruza de vuelta al padre.
    """
    t_ini = time.perf_counter()

    # El inventario se reconstruye en el hijo en vez de viajar encurtido:
    # los activos llevan objetos `random.Random` con estado, y enviarlos por
    # pickle seria mas caro y mas fragil que volver a instanciarlos.
    todos = simulador.construir_inventario(plan.seed)
    activos = [todos[i] for i in plan.indices_activos]

    ruta = Path(plan.output_dir) / f"part-{plan.worker_id:03d}.jsonl"
    sumidero = esquema.SumideroArchivo(ruta)
    try:
        eventos = esquema.bucle_worker(plan, activos, sumidero)
    finally:
        # El cierre va en `finally` para que una excepcion en la fisica no
        # deje el descriptor abierto ni el buffer de 4 MB sin volcar.
        sumidero.cerrar()

    # `stat()` DESPUES de cerrar: antes del cierre el tamano no refleja lo que
    # el sistema operativo realmente escribio.
    tam = ruta.stat().st_size
    return ResumenWorker(
        worker_id=plan.worker_id,
        archivo=ruta.name,
        eventos=eventos,
        bytes=tam,
        puntos=sum(a.n_puntos for a in activos),
        duracion_s=time.perf_counter() - t_ini,
    )


def ejecutar(plan: PlanCorrida, ctx=None, initializer=None, initargs=()) -> ResumenCorrida:
    """Orquesta la corrida completa y devuelve el resumen agregado.

    El cronometro arranca antes de crear el primer proceso y para despues de
    que el ultimo archivo esta cerrado. Incluir el costo de creacion de
    procesos no contamina la medicion: con `spawn` ese costo es precisamente
    uno de los candidatos que explican donde se aplana la curva de speedup.
    """
    ctx = ctx or mp.get_context()

    activos = simulador.construir_inventario(plan.seed)
    cubos = simulador.asignar_workers(activos, plan.workers)

    planes = [
        PlanWorker(
            worker_id=wid,
            indices_activos=indices,
            t0_ms=plan.t0_ms,
            dt_ms=plan.dt_ms,
            n_ticks=plan.n_ticks,
            seed=plan.seed,
            batch_size=plan.batch_size,
            output_dir=plan.output_dir,
            esquema=plan.esquema,
        )
        for wid, indices in enumerate(cubos)
    ]

    puntos = [sum(activos[i].n_puntos for i in c) for c in cubos]
    log.info(
        "reparto de carga: %s puntos por worker (desbalance %d)",
        puntos,
        max(puntos) - min(puntos),
    )

    t_ini = time.perf_counter()
    resultados: list[ResumenWorker] = []
    with ctx.Pool(
        processes=plan.workers, initializer=initializer, initargs=initargs
    ) as pool:
        tareas = [pool.apply_async(trabajador_shard, (p,)) for p in planes]
        for tarea in tareas:
            # `get()` relanza en el padre cualquier excepcion del hijo. Sin
            # este `get`, un worker que muere pasa completamente inadvertido
            # y el dataset queda corto en silencio.
            resultados.append(tarea.get())
    duracion = time.perf_counter() - t_ini

    resultados.sort(key=lambda r: r.worker_id)
    total_ev = sum(r.eventos for r in resultados)

    # Control de conteo: es la linea que separa un dataset entregable de un
    # criterio en cero. Es error fatal, no advertencia.
    if total_ev != plan.eventos_esperados:
        raise RuntimeError(
            f"conteo inconsistente: se esperaban {plan.eventos_esperados} eventos "
            f"y los workers reportaron {total_ev}. El dataset NO es valido."
        )

    return ResumenCorrida(
        eventos=total_ev,
        bytes=sum(r.bytes for r in resultados),
        duracion_s=duracion,
        archivos=[r.archivo for r in resultados],
        detalles=resultados,
    )
