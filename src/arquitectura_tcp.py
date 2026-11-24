"""Opcion C: cada worker envia sus eventos por TCP al receptor asincrono.

Es la arquitectura que corre en Docker Compose: el simulador vive en el
contenedor `simulador-puerto` y no escribe nada en disco; el contenedor
`ingestor-tcp` (`src/receptor_tcp.py`) es el unico que toca el volumen.

Expone la MISMA firma que `arquitectura_b.ejecutar`, de modo que `main.py`
despacha sin saber nada mas de ella. Y reutiliza el mismo `bucle_worker`:
lo unico que cambia respecto de la Opcion B es el sumidero (`SumideroTCP`
en vez de `SumideroArchivo`). Por eso produce exactamente el mismo
multiconjunto de eventos, cosa que verifica
`bench/test_formato.py::test_equivalencia_tcp`.

Por que una conexion por worker y no un socket compartido:

  * Compartir un socket entre procesos reproduciria el antipatron de la
    seccion 2.1 de la guia: dos `sendall` concurrentes pueden intercalar sus
    bytes y cortar lineas por la mitad. Con una conexion propia es imposible
    por construccion, igual que en la Opcion B.
  * No hay `pickle` en la ruta de datos: viajan los bytes de las lineas ya
    serializadas. Los unicos encurtidos son los del `PlanWorker` y el
    `ResumenWorker`, como en la Opcion B.

Su garantia de integridad es el ACUSE: despues del ultimo lote el worker
cierra su mitad de escritura (EOF) y espera a que el receptor confirme,
DESPUES de su fsync, cuantas lineas quedaron en el disco. Si no coincide con
lo enviado, el worker falla y la corrida sale con codigo distinto de cero.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from . import esquema, receptor_tcp, simulador
from .esquema import PlanCorrida, PlanWorker, ResumenCorrida, ResumenWorker

log = logging.getLogger(__name__)

#: Reintentos de conexion. Con `depends_on: condition: service_healthy` el
#: receptor ya escucha cuando el simulador arranca, pero el DNS interno o un
#: reinicio del receptor pueden tardar un instante: fallar al primer intento
#: seria fragil.
INTENTOS_CONEXION = 30
ESPERA_REINTENTO_S = 1.0

#: Tope de espera de un `sendall` bloqueado. Existe para que un receptor
#: colgado produzca un error y no un simulador congelado para siempre.
TIMEOUT_ENVIO_S = 120.0

#: El acuse llega despues del fsync del receptor, que con un archivo de
#: cientos de MB en disco mecanico puede tardar.
TIMEOUT_ACUSE_S = 300.0


@dataclass(frozen=True)
class DestinoTCP:
    """Lo que el worker necesita, ademas de su PlanWorker, para conectarse."""

    host: str
    port: int
    corrida: str
    workers: int


def conectar(host: str, port: int, intentos: int = INTENTOS_CONEXION,
             espera_s: float = ESPERA_REINTENTO_S) -> socket.socket:
    ultimo: OSError | None = None
    for i in range(1, intentos + 1):
        try:
            return socket.create_connection((host, port), timeout=10)
        except OSError as exc:
            ultimo = exc
            if i < intentos:
                logging.getLogger(__name__).warning(
                    "no se pudo conectar a %s:%d (%s); reintento %d/%d",
                    host, port, exc, i, intentos - 1)
                time.sleep(espera_s)
    raise ConnectionError(
        f"no se pudo conectar al receptor en {host}:{port} tras {intentos} "
        f"intentos: {ultimo}. Dentro de Compose el host es el NOMBRE del "
        "servicio (ingestor-tcp), no localhost, y el receptor debe escuchar "
        "en 0.0.0.0."
    ) from ultimo


def _leer_acuse(sock: socket.socket) -> dict:
    sock.settimeout(TIMEOUT_ACUSE_S)
    buf = b""
    while not buf.endswith(b"\n"):
        trozo = sock.recv(4096)
        if not trozo:
            break
        buf += trozo
    if not buf:
        raise ConnectionError("el receptor cerro la conexion sin enviar acuse")
    return receptor_tcp.parsear_acuse(buf)


def trabajador_tcp(plan: PlanWorker, destino: DestinoTCP) -> ResumenWorker:
    """Cuerpo del proceso hijo. Funcion de modulo de nivel superior por la
    misma razon que `trabajador_shard`: con `spawn` se resuelve por nombre."""
    t_ini = time.perf_counter()

    todos = simulador.construir_inventario(plan.seed)
    activos = [todos[i] for i in plan.indices_activos]
    puntos = sum(a.n_puntos for a in activos)
    esperados = puntos * plan.n_ticks

    sock = conectar(destino.host, destino.port)
    try:
        sock.settimeout(TIMEOUT_ENVIO_S)
        sock.sendall(receptor_tcp.linea_cabecera(
            plan.worker_id, esperados, destino.workers, destino.corrida))
        sumidero = esquema.SumideroTCP(sock)
        eventos = esquema.bucle_worker(plan, activos, sumidero)
        # EOF de nuestro lado: "no hay mas datos". La conexion sigue abierta
        # en el otro sentido para recibir el acuse.
        sock.shutdown(socket.SHUT_WR)
        acuse = _leer_acuse(sock)
    finally:
        sock.close()

    if not acuse.get("completo") or acuse.get("recibidos") != eventos:
        raise RuntimeError(
            f"worker {plan.worker_id}: se enviaron {eventos} eventos y el "
            f"receptor confirma {acuse.get('recibidos')} "
            f"({acuse.get('error', 'conteo distinto')})"
        )

    return ResumenWorker(
        worker_id=plan.worker_id,
        archivo=acuse.get("archivo", ""),
        eventos=eventos,
        bytes=int(acuse.get("bytes", sumidero.bytes)),
        puntos=puntos,
        duracion_s=time.perf_counter() - t_ini,
    )


def ejecutar(plan: PlanCorrida, ctx=None, initializer=None, initargs=()) -> ResumenCorrida:
    """Orquesta la corrida completa y devuelve el resumen agregado.

    Cuando retorna sin excepcion, cada evento esta confirmado por el receptor
    como escrito y sincronizado en su disco.
    """
    ctx = ctx or mp.get_context()

    # Falla temprano, en el padre y con un mensaje claro, antes de lanzar N
    # procesos que fallarian todos por lo mismo. La conexion de prueba se
    # abre y se cierra sin datos: el receptor la trata como un healthcheck.
    conectar(plan.tcp_host, plan.tcp_port).close()

    activos = simulador.construir_inventario(plan.seed)
    cubos = simulador.asignar_workers(activos, plan.workers)
    corrida = (f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
               f"-tcp-w{plan.workers}")
    destino = DestinoTCP(plan.tcp_host, plan.tcp_port, corrida, plan.workers)

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
    log.info("corrida %s -> %s:%d, reparto de carga: %s puntos por worker",
             corrida, plan.tcp_host, plan.tcp_port, puntos)

    t_ini = time.perf_counter()
    resultados: list[ResumenWorker] = []
    with ctx.Pool(
        processes=plan.workers, initializer=initializer, initargs=initargs
    ) as pool:
        tareas = [pool.apply_async(trabajador_tcp, (p, destino)) for p in planes]
        for tarea in tareas:
            # `get()` relanza en el padre la excepcion del hijo, incluida la
            # de un acuse que no cuadra.
            resultados.append(tarea.get())
    duracion = time.perf_counter() - t_ini

    resultados.sort(key=lambda r: r.worker_id)
    total_ev = sum(r.eventos for r in resultados)
    if total_ev != plan.eventos_esperados:
        raise RuntimeError(
            f"conteo inconsistente: se esperaban {plan.eventos_esperados} eventos "
            f"y el receptor confirmo {total_ev}. El dataset NO es valido."
        )

    return ResumenCorrida(
        eventos=total_ev,
        bytes=sum(r.bytes for r in resultados),
        duracion_s=duracion,
        archivos=[r.archivo for r in resultados],
        detalles=resultados,
    )
