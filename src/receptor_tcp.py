"""Receptor TCP asincrono del TPC Sitio 3 (servicio `ingestor-tcp`).

Escucha conexiones TCP, recibe eventos en JSON Lines y los persiste en
`DATA_DIR` como archivos .jsonl. Es el otro extremo de `--arch tcp` del
simulador: cada worker abre su propia conexion y el receptor escribe un
`part-NNN.jsonl` por worker.

    python src/receptor_tcp.py                     # 0.0.0.0:9009 -> data/raw
    BIND_HOST=127.0.0.1 TCP_PORT=9009 DATA_DIR=data/raw python src/receptor_tcp.py

Es un modulo AUTOCONTENIDO, solo biblioteca estandar y sin imports relativos:
tiene que poder ejecutarse como script (`python src/receptor_tcp.py`, que es
lo que hace el CMD del Dockerfile) y tambien importarse desde el simulador,
que toma de aqui las funciones del protocolo.

--------------------------------------------------------------------------
Protocolo (una conexion = un worker)
--------------------------------------------------------------------------
  1. cliente -> servidor: una linea de CABECERA
       {"protocolo":"tpc-s3/1","worker_id":3,"eventos":2500002,
        "workers":4,"corrida":"20260925T120000-tcp-w4"}
  2. cliente -> servidor: las lineas de eventos, tal cual iran al disco.
  3. cliente: shutdown(SHUT_WR). El EOF significa "no hay mas datos".
  4. servidor: flush + fsync + close del archivo, y SOLO DESPUES responde
     una linea de ACUSE con lo que realmente quedo en disco:
       {"protocolo":"tpc-s3/1","worker_id":3,"recibidos":2500002,
        "bytes":465000372,"archivo":"part-003.jsonl","completo":true}

El acuse es lo que convierte "envie los datos" en "los datos estan en el
disco": el simulador no termina con codigo 0 hasta que cada worker recibio el
suyo y el conteo coincide. Sin el, el simulador podria salir mientras los
ultimos megabytes siguen en los buffers del socket o en el buffer del archivo,
y un `wc -l` inmediato contaria de menos.

Una conexion que se abre y se cierra sin enviar nada (el healthcheck de
Compose, cada 5 s) se descarta en silencio. Una conexion cuya primera linea
no es una cabecera valida se acepta igual, como `anon-NNNN.jsonl`: sirve para
depurar a mano con `nc localhost 9009`.

--------------------------------------------------------------------------
Apagado limpio (SIGTERM)
--------------------------------------------------------------------------
`docker stop` y `docker compose down` envian SIGTERM y esperan el
`stop_grace_period` antes de mandar SIGKILL. Al recibir SIGTERM el receptor:
deja de aceptar conexiones, corta las activas, escribe las lineas COMPLETAS
que ya habia recibido, hace flush + fsync, registra en el manifiesto que esos
archivos quedaron interrumpidos y termina con codigo 143 (128 + 15), la
convencion de "terminado por SIGTERM". Un fragmento de linea a medio llegar
se descarta: un .jsonl con una ultima linea cortada romperia al lector de la
Fase 2, uno con menos lineas pero todas validas no.

En asyncio la senal se atiende con `loop.add_signal_handler` y no con
`signal.signal`: el manejador de `signal.signal` interrumpe al bucle en un
punto arbitrario, mientras que `add_signal_handler` lo encola como una
llamada mas del propio bucle, entre dos `await`, con el estado consistente.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Protocolo: lo unico que el simulador importa de este modulo
# ---------------------------------------------------------------------------

PROTOCOLO = "tpc-s3/1"

#: Tamano de cada `read()` sobre el socket. Leer por bloques y no por lineas
#: es lo que hace barato al receptor: ~1.900 lecturas para 1,9 GB en vez de
#: diez millones de `readline()`, y el conteo de lineas lo hace
#: `bytes.count`, en C.
TAM_LECTURA = 1 << 20  # 1 MiB

#: Buffer del archivo de salida: amortiza las syscalls `write`.
TAM_BUFFER_ARCHIVO = 4 << 20  # 4 MiB

#: Una linea sin terminar mas larga que esto no es un evento: es basura o un
#: cliente que no habla el protocolo. Evita que un cliente roto haga crecer
#: el fragmento pendiente sin limite.
MAX_FRAGMENTO = 1 << 20

MANIFIESTO = "manifiesto_receptor.json"


def _linea(obj: dict) -> bytes:
    return (json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def linea_cabecera(worker_id: int, eventos: int, workers: int, corrida: str) -> bytes:
    """Primera linea que envia cada worker del simulador."""
    return _linea({
        "protocolo": PROTOCOLO, "worker_id": worker_id, "eventos": eventos,
        "workers": workers, "corrida": corrida,
    })


def parsear_cabecera(linea: bytes) -> dict | None:
    """Devuelve la cabecera si `linea` lo es; None si es un evento cualquiera."""
    try:
        d = json.loads(linea)
    except (ValueError, UnicodeDecodeError):
        return None
    if not (isinstance(d, dict) and d.get("protocolo") == PROTOCOLO):
        return None
    try:
        d["worker_id"] = int(d["worker_id"])
        d["eventos"] = int(d["eventos"])
    except (KeyError, TypeError, ValueError):
        return None
    return d


def parsear_acuse(linea: bytes) -> dict:
    """Lo usa el simulador para leer la respuesta del receptor."""
    d = json.loads(linea)
    if not (isinstance(d, dict) and d.get("protocolo") == PROTOCOLO):
        raise ValueError(f"acuse fuera de protocolo: {linea[:200]!r}")
    return d


# ---------------------------------------------------------------------------
# Estado del receptor
# ---------------------------------------------------------------------------

log = logging.getLogger("receptor")


class Conexion:
    """Un archivo de salida abierto por una conexion.

    Solo escribe LINEAS COMPLETAS: el llamador le entrega bloques que
    terminan en '\\n'. Es la condicion para que el archivo quede valido pase
    lo que pase con el socket.
    """

    __slots__ = ("nombre", "ruta", "worker_id", "anunciados", "lineas",
                 "bytes", "t_ini", "_f", "estado")

    def __init__(self, ruta: Path, worker_id: int | None, anunciados: int | None):
        self.nombre = ruta.name
        self.ruta = ruta
        self.worker_id = worker_id
        self.anunciados = anunciados
        self.lineas = 0
        self.bytes = 0
        self.t_ini = time.monotonic()
        self.estado = "recibiendo"
        # "wb": una conexion nueva del mismo worker reemplaza el archivo en
        # vez de duplicar los datos al final, asi re-ejecutar el simulador no
        # deja 20 millones de lineas.
        self._f = open(ruta, "wb", buffering=TAM_BUFFER_ARCHIVO)

    def escribir(self, datos, n_lineas: int) -> None:
        self._f.write(datos)
        self.lineas += n_lineas
        self.bytes += len(datos)

    def vaciar(self) -> None:
        """flush + fsync. Lo que devuelve esta funcion ya esta en el disco,
        no en el buffer de Python ni en la cache de paginas del kernel."""
        if not self._f.closed:
            self._f.flush()
            os.fsync(self._f.fileno())

    def cerrar(self) -> None:
        if not self._f.closed:
            self.vaciar()
            self._f.close()

    def resumen(self) -> dict:
        dur = time.monotonic() - self.t_ini
        return {
            "archivo": self.nombre,
            "worker_id": self.worker_id,
            "anunciados": self.anunciados,
            "recibidos": self.lineas,
            "bytes": self.bytes,
            "estado": self.estado,
            "completo": self.estado == "completo",
            "duracion_s": round(dur, 3),
            "mb_por_segundo": round(self.bytes / 1e6 / dur, 2) if dur > 0 else None,
        }


class Receptor:
    def __init__(self, data_dir: Path, reporte_s: float) -> None:
        self.data_dir = data_dir
        self.reporte_s = reporte_s
        self.total_lineas = 0
        self.total_bytes = 0
        self.n_conexiones = 0
        self.abiertos: dict[str, Conexion] = {}
        self.tareas: set[asyncio.Task] = set()
        self.corrida: str | None = None
        self.workers_anunciados: int | None = None
        self.archivos: dict[str, dict] = {}

    # --- manifiesto ---------------------------------------------------------

    def escribir_manifiesto(self) -> None:
        """Estado de lo recibido, en el mismo disco que los datos.

        Se reescribe completo en cada cierre de conexion y se reemplaza de
        forma atomica: un `docker kill` a mitad de la escritura deja el
        manifiesto anterior, nunca uno truncado.
        """
        archivos = sorted(self.archivos.values(), key=lambda a: a["archivo"])
        doc = {
            "actualizado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "protocolo": PROTOCOLO,
            "corrida": self.corrida,
            "workers_anunciados": self.workers_anunciados,
            "total_recibido": sum(a["recibidos"] for a in archivos),
            "total_bytes": sum(a["bytes"] for a in archivos),
            "archivos_completos": sum(1 for a in archivos if a["completo"]),
            "archivos": archivos,
        }
        tmp = self.data_dir / (MANIFIESTO + ".tmp")
        tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.data_dir / MANIFIESTO)

    def _nueva_corrida(self, cab: dict) -> None:
        corrida = str(cab.get("corrida", ""))
        if corrida == self.corrida:
            return
        self.corrida = corrida
        self.archivos = {}
        try:
            self.workers_anunciados = int(cab.get("workers"))
        except (TypeError, ValueError):
            self.workers_anunciados = None
        log.info("corrida nueva: %s (%s workers)", corrida, self.workers_anunciados)
        # Aviso, no borrado: si quedaron shards de una corrida anterior con
        # MAS workers, `wc -l data/raw/*.jsonl` los sumaria. Borrar datos
        # automaticamente no es trabajo de un receptor.
        if self.workers_anunciados:
            sobrantes = sorted(
                p.name for p in self.data_dir.glob("part-*.jsonl")
                if p.stem[5:].isdigit() and int(p.stem[5:]) >= self.workers_anunciados
            )
            if sobrantes:
                log.warning("hay archivos de una corrida anterior que no se van a "
                            "sobrescribir: %s. Borrelos antes de contar.", sobrantes)

    # --- una conexion -------------------------------------------------------

    async def atender(self, reader: asyncio.StreamReader,
                      writer: asyncio.StreamWriter) -> None:
        self.n_conexiones += 1
        cid = self.n_conexiones
        tarea = asyncio.current_task()
        self.tareas.add(tarea)
        peer = writer.get_extra_info("peername")
        conn: Conexion | None = None
        try:
            try:
                primera = await reader.readline()
            except (ValueError, asyncio.LimitOverrunError):
                log.warning("conexion %d desde %s: primera linea demasiado larga",
                            cid, peer)
                return
            if not primera:
                # Abrio y cerro sin enviar nada: el healthcheck de Compose.
                log.debug("conexion %d desde %s sin datos (healthcheck)", cid, peer)
                return

            cab = parsear_cabecera(primera)
            if cab is not None:
                self._nueva_corrida(cab)
                nombre = f"part-{cab['worker_id']:03d}.jsonl"
                anunciados = cab["eventos"]
                wid = cab["worker_id"]
            else:
                nombre = f"anon-{cid:04d}.jsonl"
                anunciados = None
                wid = None

            if nombre in self.abiertos:
                # Dos conexiones con el mismo worker_id se pisarian el archivo.
                log.error("conexion %d: %s ya esta siendo escrito por otra "
                          "conexion; se rechaza", cid, nombre)
                writer.write(_linea({"protocolo": PROTOCOLO, "worker_id": wid,
                                     "completo": False,
                                     "error": f"{nombre} ocupado"}))
                await writer.drain()
                return

            conn = Conexion(self.data_dir / nombre, wid, anunciados)
            self.abiertos[nombre] = conn
            log.info("conexion %d desde %s -> %s (%s eventos anunciados)",
                     cid, peer, nombre, anunciados if anunciados is not None else "?")
            if cab is None and primera.endswith(b"\n"):
                self._escribir(conn, primera, 1)
            pendiente = b"" if cab is not None or primera.endswith(b"\n") else primera

            while True:
                bloque = await reader.read(TAM_LECTURA)
                if not bloque:
                    break
                datos = pendiente + bloque if pendiente else bloque
                # Se escribe hasta el ULTIMO salto de linea del bloque; el resto
                # es el comienzo de una linea que termina en el proximo read.
                corte = datos.rfind(b"\n") + 1
                if corte:
                    self._escribir(conn, memoryview(datos)[:corte],
                                   datos.count(b"\n", 0, corte))
                    pendiente = datos[corte:]
                else:
                    pendiente = datos
                if len(pendiente) > MAX_FRAGMENTO:
                    raise ValueError(f"linea de mas de {MAX_FRAGMENTO} bytes sin '\\n'")

            if pendiente:
                # EOF en mitad de una linea: el cliente la envio sin '\n' final.
                log.warning("%s: ultima linea sin salto de linea; se completa", nombre)
                self._escribir(conn, pendiente + b"\n", 1)

            # fsync en un hilo: puede tardar segundos con un archivo grande y
            # bloquear el bucle congelaria a TODAS las demas conexiones.
            conn.estado = "cerrando"
            await asyncio.to_thread(conn.cerrar)
            completo = anunciados is None or conn.lineas == anunciados
            conn.estado = "completo" if completo else "incompleto"
            res = conn.resumen()
            (log.info if completo else log.error)(
                "%s cerrado: %d/%s eventos, %.1f MB en %.1f s (%s)",
                nombre, conn.lineas, anunciados if anunciados is not None else "?",
                conn.bytes / 1e6, res["duracion_s"], conn.estado,
            )
            writer.write(_linea({"protocolo": PROTOCOLO, "worker_id": wid,
                                 "recibidos": conn.lineas, "bytes": conn.bytes,
                                 "archivo": nombre, "completo": completo}))
            await writer.drain()

        except asyncio.CancelledError:
            # Apagado por SIGTERM con la conexion a medio recibir. Lo escrito
            # son lineas completas; se vacia y se deja constancia.
            if conn is not None:
                if conn.estado != "cerrando":
                    # Si ya estaba "cerrando", el fsync corre en su hilo y
                    # asyncio.run espera a ese hilo antes de salir: cerrar
                    # aqui tambien seria cerrar dos veces desde dos hilos.
                    conn.cerrar()
                conn.estado = "interrumpido"
                log.warning("%s interrumpido por el apagado: %d eventos persistidos",
                            conn.nombre, conn.lineas)
            raise
        except (ConnectionError, ValueError, OSError) as exc:
            if conn is not None:
                conn.estado = "error"
                conn.cerrar()
            log.error("conexion %d desde %s fallo: %s: %s", cid, peer,
                      type(exc).__name__, exc)
        finally:
            if conn is not None:
                self.abiertos.pop(conn.nombre, None)
                self.archivos[conn.nombre] = conn.resumen()
                try:
                    self.escribir_manifiesto()
                except OSError as exc:
                    log.error("no se pudo escribir el manifiesto: %s", exc)
            self.tareas.discard(tarea)
            writer.close()

    def _escribir(self, conn: Conexion, datos, n: int) -> None:
        conn.escribir(datos, n)
        self.total_lineas += n
        self.total_bytes += len(datos)

    # --- progreso -----------------------------------------------------------

    async def reportar(self) -> None:
        """Progreso de la ingesta cada `reporte_s` segundos, solo si cambio.

        Con PYTHONUNBUFFERED=1 esto aparece en `docker compose logs -f` en el
        momento en que ocurre, no al final.
        """
        previo, t_prev = self.total_lineas, time.monotonic()
        while True:
            await asyncio.sleep(self.reporte_s)
            ahora = time.monotonic()
            if self.total_lineas != previo:
                tasa = (self.total_lineas - previo) / (ahora - t_prev)
                log.info("progreso: %s eventos | %.1f MB | %s ev/s | %d conexiones activas",
                         f"{self.total_lineas:,}", self.total_bytes / 1e6,
                         f"{tasa:,.0f}", len(self.abiertos))
            previo, t_prev = self.total_lineas, ahora


# ---------------------------------------------------------------------------
# Servidor
# ---------------------------------------------------------------------------


async def servir(host: str, puerto: int, data_dir: Path, reporte_s: float,
                 listo: asyncio.Event | None = None) -> int:
    """Corre hasta recibir SIGTERM o SIGINT. Devuelve el codigo de salida."""
    receptor = Receptor(data_dir, reporte_s)
    loop = asyncio.get_running_loop()
    detener = asyncio.Event()
    recibida: list[int] = []

    def _al_recibir(signum: int) -> None:
        recibida.append(signum)
        detener.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _al_recibir, sig)

    # `limit` fija el tope del buffer del StreamReader: con 1 MiB, cada read()
    # devuelve bloques grandes y el transporte deja de leer del socket (TCP
    # le frena el envio al simulador) cuando hay ~2 MiB sin consumir. Esa es
    # la contrapresion de este lado: la RAM del receptor no crece con la
    # velocidad del emisor.
    server = await asyncio.start_server(receptor.atender, host, puerto,
                                        limit=TAM_LECTURA, reuse_address=True)
    direcciones = ", ".join(f"{s.getsockname()[0]}:{s.getsockname()[1]}"
                            for s in server.sockets)
    log.info("escuchando en %s | escribiendo en %s | pid %d",
             direcciones, data_dir.resolve(), os.getpid())
    if listo is not None:
        listo.set()

    reporte = asyncio.create_task(receptor.reportar())
    await detener.wait()

    nombre = signal.Signals(recibida[0]).name
    log.info("%s recibido: cerrando sockets y haciendo flush del .jsonl", nombre)
    server.close()
    reporte.cancel()
    activas = list(receptor.tareas)
    for t in activas:
        t.cancel()
    await asyncio.gather(*activas, return_exceptions=True)
    try:
        # Desde 3.12 wait_closed espera a que cierren todas las conexiones;
        # ya se cancelaron, pero se acota por si alguna quedo colgada.
        await asyncio.wait_for(server.wait_closed(), timeout=5)
    except asyncio.TimeoutError:
        log.warning("el servidor no termino de cerrar en 5 s")
    log.info("apagado limpio: %s eventos persistidos en esta sesion",
             f"{receptor.total_lineas:,}")
    # 128 + numero de senal: la convencion de "termine por SIGTERM", que es
    # lo que `docker inspect` muestra como ExitCode=143. Aqui significa
    # "termine por SIGTERM DESPUES de vaciar los buffers".
    return 128 + recibida[0]


def _entorno(nombre: str, defecto: str) -> str:
    valor = os.environ.get(nombre, "")
    return valor if valor else defecto


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python src/receptor_tcp.py",
        description="Receptor TCP asincrono del TPC Sitio 3. Cada opcion toma "
                    "su valor por defecto de la variable de entorno indicada.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--host", default=_entorno("BIND_HOST", "0.0.0.0"),
                   help="direccion de escucha (env BIND_HOST). Dentro de un "
                        "contenedor TIENE que ser 0.0.0.0: 127.0.0.1 es el "
                        "loopback del propio contenedor y nadie mas llega")
    p.add_argument("--port", type=int, default=int(_entorno("TCP_PORT", "9009")),
                   help="puerto TCP (env TCP_PORT)")
    p.add_argument("--data-dir", default=_entorno("DATA_DIR", "data/raw"),
                   help="carpeta donde se escriben los .jsonl (env DATA_DIR)")
    p.add_argument("--reporte-s", type=float,
                   default=float(_entorno("REPORTE_S", "5")),
                   help="segundos entre lineas de progreso (env REPORTE_S)")
    p.add_argument("--log-level", default=_entorno("LOG_LEVEL", "INFO"),
                   choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    return p


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level), stream=sys.stdout,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    data_dir = Path(args.data_dir)
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        prueba = data_dir / ".escritura"
        prueba.write_bytes(b"")
        prueba.unlink()
    except PermissionError:
        # El error mas comun al endurecer la imagen: el contenedor escribe
        # como UID 10001 y el bind mount del host pertenece a otro usuario.
        log.error("sin permiso de escritura en %s (uid %d). En el host: "
                  "sudo chown -R 10001:10001 <carpeta montada>",
                  data_dir.resolve(), os.getuid())
        return 1
    try:
        return asyncio.run(servir(args.host, args.port, data_dir, args.reporte_s))
    except OSError as exc:
        log.error("no se pudo escuchar en %s:%d: %s", args.host, args.port, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
