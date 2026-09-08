"""Opcion A: proceso escritor unico alimentado por multiprocessing.Queue.

Separa el rol de calcular del rol de escribir (guia, seccion 2.2). Los N
trabajadores hacen la fisica y la serializacion; un proceso dedicado, el
escritor, es el unico que tiene el archivo abierto y escribe de manera
secuencial. La comunicacion va por una cola multiproceso, segura por
construccion.

Expone la MISMA firma que `arquitectura_b.ejecutar`, de modo que `main.py`
despacha con un `if` de dos lineas y no sabe nada mas sobre la arquitectura.

--------------------------------------------------------------------------
Por que NO se usa multiprocessing.Pool aqui
--------------------------------------------------------------------------
Una `mp.Queue` no se puede pasar como argumento a `Pool.apply_async`: CPython
lanza `RuntimeError` porque las colas solo se comparten por herencia, al
crear el proceso. Por eso esta arquitectura se orquesta con objetos
`mp.Process` explicitos. Es la razon tecnica de que A y B no puedan compartir
orquestador aunque compartan el bucle de generacion.

Relacionado, la Trampa N.o 2 de la guia: `queue.Queue` tampoco cruza el
limite entre procesos. Si se usa por error, cada hijo recibe una copia vacia
y escribe en el vacio. No hay excepcion, no hay error: el archivo final queda
con cero lineas y el programa termina feliz.

--------------------------------------------------------------------------
Los tres modos de falla y como se cubren
--------------------------------------------------------------------------
1. DESBORDE DE MEMORIA. Si los workers producen mas rapido de lo que el disco
   sostiene, la diferencia no desaparece: se acumula en el buffer de la cola,
   que vive en RAM. Por eso la cola se crea con `maxsize` acotado: cuando se
   llena, `put` bloquea, los trabajadores se frenan solos y el sistema se
   autorregula al ritmo del disco. Esa contrapresion no es una limitacion, es
   la caracteristica que hace utilizable el patron.

2. WORKER QUE MUERE SIN ENVIAR SU CENTINELA. El escritor nunca llegaria a
   cero vivos y se quedaria bloqueado para siempre en `get`, y el padre en
   `join`. Cubierto en dos capas: el centinela se emite en un `finally`, que
   atrapa cualquier excepcion de Python; y para lo que el `finally` NO cubre
   -un SIGKILL del OOM killer, donde no corre ningun codigo del hijo- el
   padre vigila los `exitcode` y activa el evento de aborto.

3. ESCRITOR QUE MUERE. Nadie drena la cola, se llena hasta `maxsize`, y todos
   los workers quedan bloqueados en `put` sin lanzar nada. Desde afuera es
   indistinguible de estar trabajando duro. Cubierto por el `put(timeout=...)`
   de `SumideroCola`, que consulta el evento de aborto en cada reintento, mas
   la supervision activa del padre.

--------------------------------------------------------------------------
Nota sobre reproducibilidad
--------------------------------------------------------------------------
Esta arquitectura NO puede producir un archivo byte a byte identico entre dos
corridas: el orden en que los lotes de distintos workers llegan al escritor
lo decide el planificador del sistema operativo. Lo que si es identico es el
CONJUNTO de eventos: mismos datos, distinto orden de lineas. La Opcion B, en
cambio, si es identica byte a byte. La verificacion esta en
`bench/test_formato.py::test_equivalencia_arquitecturas`, que compara las
lineas ordenadas de ambas salidas.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import queue as _queue
import time
from pathlib import Path

from . import esquema, simulador
from .esquema import (
    AbortoSolicitado, PlanCorrida, PlanWorker, ResumenCorrida, ResumenWorker,
)

log = logging.getLogger(__name__)

#: Marca de termino de un worker. Es una cadena y no None para que no se
#: confunda con un lote vacio legitimo.
CENTINELA = "__FIN__"

#: Cada cuanto despiertan `put` y `get` para consultar el evento de aborto.
#: No es un timeout de fallo: es la granularidad con que los procesos
#: bloqueados se enteran de que alguien mas murio.
LATIDO_S = 1.0


# ---------------------------------------------------------------------------
# Procesos hijos
# ---------------------------------------------------------------------------


def _proceso_worker(plan: PlanWorker, cola, cola_resultados, aborto,
                    initializer=None, initargs=()) -> None:
    """Genera eventos y los encola. Nunca toca el archivo de salida.

    Debe ser una funcion de modulo de nivel superior: con `spawn` el hijo
    reimporta el modulo y resuelve el destino por nombre.
    """
    if initializer is not None:
        initializer(*initargs)

    t_ini = time.perf_counter()
    eventos = 0
    error = ""
    puntos = 0
    try:
        todos = simulador.construir_inventario(plan.seed)
        activos = [todos[i] for i in plan.indices_activos]
        puntos = sum(a.n_puntos for a in activos)
        sumidero = esquema.SumideroCola(cola, aborto, timeout=LATIDO_S)
        eventos = esquema.bucle_worker(plan, activos, sumidero)
    except AbortoSolicitado:
        error = "abortado por el proceso padre"
        # Al abortar puede quedar un lote a medio enviar en el buffer interno
        # de la cola. Sin esto, el proceso se cuelga AL SALIR: `Queue` hace
        # join sobre su hilo alimentador, que a su vez esta bloqueado en el
        # `write()` de un pipe que nadie va a leer. Los datos pendientes se
        # descartan a proposito; la corrida ya es invalida.
        cola.cancel_join_thread()
    except Exception as exc:  # noqa: BLE001 - se reporta al padre, no se traga
        error = f"{type(exc).__name__}: {exc}"
        logging.getLogger(__name__).exception("worker %d fallo", plan.worker_id)
    finally:
        # El centinela va en el `finally` para que se emita tambien cuando el
        # bucle termina por excepcion. Sin el, el escritor esperaria un
        # centinela que nunca llega y el programa no terminaria jamas.
        try:
            cola.put(CENTINELA, timeout=LATIDO_S)
        except _queue.Full:
            pass  # el escritor ya murio; el padre lo detecta por exitcode
        cola_resultados.put({
            "tipo": "worker", "worker_id": plan.worker_id, "eventos": eventos,
            "puntos": puntos, "duracion_s": time.perf_counter() - t_ini,
            "error": error,
        })


def _proceso_escritor(cola, cola_resultados, aborto, ruta: str, n_workers: int,
                      initializer=None, initargs=()) -> None:
    """Unico proceso con el archivo abierto. Solo hace `writelines`.

    Lleva la cuenta de centinelas: un worker menos cada vez, y se sigue con el
    resto. Cuando `vivos` llega a cero puede cerrar el archivo con la certeza
    de que nadie mas va a escribir. Un centinela global unico no serviria: el
    worker que termina primero no tiene forma de saber si los otros siguen
    produciendo.
    """
    if initializer is not None:
        initializer(*initargs)

    vivos = n_workers
    lineas = 0
    error = ""
    p = Path(ruta)
    f = open(p, "w", encoding="utf-8", newline="\n", buffering=1024 * 1024)
    try:
        while vivos:
            try:
                item = cola.get(timeout=LATIDO_S)
            except _queue.Empty:
                # El timeout no significa fallo: es la oportunidad de mirar si
                # el padre pidio abortar porque un worker murio de un SIGKILL
                # y su centinela nunca va a llegar.
                if aborto.is_set():
                    error = "abortado antes de recibir todos los centinelas"
                    break
                continue
            if item == CENTINELA:
                vivos -= 1
                continue
            f.writelines(item)  # llega ya serializado, sin trabajo extra
            lineas += len(item)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
        logging.getLogger(__name__).exception("el escritor fallo")
    finally:
        f.close()  # cierre ordenado: vuelca el buffer pase lo que pase
        cola_resultados.put({
            "tipo": "escritor", "lineas": lineas, "archivo": p.name,
            "bytes": p.stat().st_size if p.exists() else 0, "error": error,
        })


# ---------------------------------------------------------------------------
# Orquestacion
# ---------------------------------------------------------------------------


def _drenar(cola) -> None:
    """Vacia la cola de datos una vez, sin bloquear."""
    try:
        while True:
            cola.get_nowait()
    except (_queue.Empty, OSError, ValueError):
        pass


def _apagar(cola, procesos, plazo: float = 10.0) -> None:
    """Apagado de emergencia: drena mientras espera.

    Un solo `_drenar` seguido de `join` no basta. Los workers que despiertan
    del aborto vuelven a llenar la cola al emitir su centinela, y un proceso
    con datos pendientes en la cola no puede terminar: `Queue` hace join sobre
    su hilo alimentador, bloqueado escribiendo en un pipe que nadie lee. Por
    eso se drena en bucle hasta que todos mueren, y solo entonces se recurre a
    `terminate`.
    """
    fin = time.monotonic() + plazo
    while time.monotonic() < fin:
        _drenar(cola)
        if not any(p.is_alive() for p in procesos):
            break
        time.sleep(0.05)
    for p in procesos:
        if p.is_alive():
            p.terminate()
        p.join(timeout=5.0)


def ejecutar(plan: PlanCorrida, ctx=None, initializer=None, initargs=()) -> ResumenCorrida:
    # Firma identica a la de `arquitectura_b.ejecutar` a proposito: es el
    # contrato que permite que `main.py` despache con un solo `if`.
    ctx = ctx or mp.get_context()

    activos = simulador.construir_inventario(plan.seed)
    cubos = simulador.asignar_workers(activos, plan.workers)
    planes = [
        PlanWorker(
            worker_id=wid, indices_activos=indices, t0_ms=plan.t0_ms,
            dt_ms=plan.dt_ms, n_ticks=plan.n_ticks, seed=plan.seed,
            batch_size=plan.batch_size, output_dir=plan.output_dir,
            esquema=plan.esquema,
        )
        for wid, indices in enumerate(cubos)
    ]
    puntos_por_worker = [sum(activos[i].n_puntos for i in c) for c in cubos]
    log.info("reparto de carga: %s puntos por worker (desbalance %d)",
             puntos_por_worker, max(puntos_por_worker) - min(puntos_por_worker))

    # maxsize acotado, NUNCA ilimitado. Ojo con las unidades: maxsize cuenta
    # MENSAJES, no eventos. El techo de RAM de la cola es aproximadamente
    # maxsize x batch_size x bytes_por_evento.
    cola = ctx.Queue(maxsize=plan.queue_maxsize)
    cola_resultados = ctx.Queue()
    aborto = ctx.Event()
    ruta = Path(plan.output_dir) / "eventos.jsonl"
    log.info("cola: maxsize=%d mensajes de hasta %d eventos", plan.queue_maxsize,
             plan.batch_size)

    t_ini = time.perf_counter()
    escritor = ctx.Process(
        target=_proceso_escritor,
        args=(cola, cola_resultados, aborto, str(ruta), plan.workers,
              initializer, initargs),
        name="escritor",
    )
    escritor.start()
    workers = [
        ctx.Process(target=_proceso_worker,
                    args=(p, cola, cola_resultados, aborto, initializer, initargs),
                    name=f"worker-{p.worker_id}")
        for p in planes
    ]
    for w in workers:
        w.start()

    # Se recogen los resultados ANTES de hacer join. Es obligatorio: un proceso
    # que dejo items sin leer en una cola se bloquea al terminar, esperando a
    # que su hilo alimentador vacie el pipe. Hacer join primero es el deadlock
    # clasico de multiprocessing.
    recogidos: list[dict] = []
    fallo = ""
    esperados = plan.workers + 1
    while len(recogidos) < esperados:
        try:
            recogidos.append(cola_resultados.get(timeout=0.5))
            continue
        except _queue.Empty:
            pass
        # --- supervision activa: aqui es donde el padre se entera -----------
        if escritor.exitcode not in (None, 0):
            fallo = (f"el proceso escritor murio con codigo {escritor.exitcode} "
                     "(probable OOM killer o segfault)")
            break
        muertos = [w for w in workers if w.exitcode not in (None, 0)]
        if muertos:
            fallo = ("murieron sin reportar: "
                     + ", ".join(f"{w.name} (codigo {w.exitcode})" for w in muertos))
            break

    if fallo:
        # Desbloquear a todo el mundo antes de terminar, o el `terminate` se
        # queda esperando a procesos atascados en `put`.
        aborto.set()
        _apagar(cola, (*workers, escritor))
        raise RuntimeError(f"la corrida con --arch queue fallo: {fallo}")

    for p in (*workers, escritor):
        p.join(timeout=60.0)
        if p.is_alive():
            aborto.set()
            _apagar(cola, (*workers, escritor))
            raise RuntimeError(f"{p.name} no termino tras reportar su resultado")
    duracion = time.perf_counter() - t_ini

    res_workers = sorted((r for r in recogidos if r["tipo"] == "worker"),
                         key=lambda r: r["worker_id"])
    res_escritor = next(r for r in recogidos if r["tipo"] == "escritor")

    errores = [r for r in (*res_workers, res_escritor) if r["error"]]
    if errores:
        raise RuntimeError("procesos con error: "
                           + "; ".join(str(e["error"]) for e in errores))

    total_ev = sum(r["eventos"] for r in res_workers)
    # Mismo control de conteo que la Opcion B...
    if total_ev != plan.eventos_esperados:
        raise RuntimeError(
            f"conteo inconsistente: se esperaban {plan.eventos_esperados} eventos "
            f"y los workers reportaron {total_ev}. El dataset NO es valido."
        )
    # ...mas uno propio de esta arquitectura: lo que los workers dicen haber
    # generado tiene que coincidir con lo que el escritor dice haber escrito.
    if res_escritor["lineas"] != total_ev:
        raise RuntimeError(
            f"el escritor grabo {res_escritor['lineas']} lineas pero los workers "
            f"generaron {total_ev}. Se perdieron lotes en la cola."
        )

    # En la Opcion A los bytes los conoce el escritor, no los workers: es la
    # unica asimetria real del contrato entre ambas arquitecturas. Se prorratean
    # por eventos para que `ResumenWorker.bytes` tenga un valor interpretable en
    # el manifiesto, y queda dicho aqui que es un prorrateo y no una medicion.
    bytes_tot = res_escritor["bytes"]
    detalles = [
        ResumenWorker(
            worker_id=r["worker_id"], archivo=res_escritor["archivo"],
            eventos=r["eventos"],
            bytes=round(bytes_tot * r["eventos"] / total_ev) if total_ev else 0,
            puntos=r["puntos"], duracion_s=r["duracion_s"],
        )
        for r in res_workers
    ]

    return ResumenCorrida(
        eventos=total_ev, bytes=bytes_tot, duracion_s=duracion,
        archivos=[res_escritor["archivo"]], detalles=detalles,
    )
