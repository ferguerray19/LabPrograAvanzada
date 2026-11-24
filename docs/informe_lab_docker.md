# Laboratorio Docker — Dockerización y orquestación del simulador multiproceso y el receptor TCP asíncrono

| Campo | Detalle |
|---|---|
| Asignatura | Programación Avanzada |
| Integrantes | _completar_ |
| Fecha | _completar_ |
| Repositorio | `ferguerray19/LabPrograAvanzada` |

> **Sobre las cifras.** Todas las mediciones de este informe salen de los scripts
> `lab/parte1.sh`, `lab/parte2.sh`, `lab/parte3.sh` y `lab/limite_ingestor.sh`,
> que dejan la salida completa en `lab/evidencias/`. Se tomaron en el entorno de la
> tabla siguiente. **Si se vuelven a correr en otro equipo, se reemplazan las cifras
> y las capturas por las nuevas**: los scripts regeneran las tablas solas.

| Entorno de medición | |
|---|---|
| Sistema | Linux 6.18 x86_64, 4 vCPU, 15 GiB de RAM, sin swap |
| Docker | Engine 29.3.1, Compose v5.1.1, BuildKit, cgroups **v1** |
| Imágenes base | `python:3.12` y `python:3.12-slim` (Debian 13 «trixie»), descargadas antes de medir |

---

## 0. La solución que se contenerizó

```
 simulador-puerto (N procesos)                         ingestor-tcp (asyncio)
 ┌──────────────────────────┐   red privada red-datos-lab   ┌────────────────────────┐
 │ worker 0 ── socket TCP ──┼──────────────────────────────►│ part-000.jsonl         │
 │ worker 1 ── socket TCP ──┼──────────────────────────────►│ part-001.jsonl         │   bind mount
 │ ...                      │     ingestor-tcp:9009 (DNS)   │ ...                    ├──► ./data/raw
 │ worker N ── socket TCP ──┼──────────────────────────────►│ manifiesto_receptor.json│   (host)
 └──────────────────────────┘ ◄── acuse tras fsync ─────────└────────────────────────┘
```

- **Simulador** (`python -m src.main --arch tcp`): el mismo generador multiproceso de la
  Fase 1. La arquitectura nueva (`src/arquitectura_tcp.py`, «Opción C») solo cambia el
  *sumidero*: en vez de escribir un archivo, cada worker envía sus lotes por **su propia**
  conexión TCP. No hay recurso compartido entre procesos ni `pickle` en la ruta de datos.
- **Receptor** (`src/receptor_tcp.py`): servidor `asyncio` que escribe un `part-NNN.jsonl`
  por worker. Lee por bloques de 1 MiB y solo escribe **líneas completas**.
- **Protocolo con acuse**: cada worker envía una cabecera con cuántos eventos va a mandar,
  los eventos, y cierra su mitad de escritura. El receptor hace `flush` + `fsync` y recién
  entonces responde cuántas líneas quedaron en disco. El simulador sale con código 0 solo
  si todos los acuses coinciden: *«terminó bien» significa «está en el disco»*.
- Verificado por `bench/test_formato.py::test_equivalencia_tcp`: los archivos que escribe
  el receptor son **idénticos byte a byte** a los de la Opción B de la Fase 1.

---

## 1. Parte 1 — Aislamiento por namespaces y red (entregable 1)

**Evidencia:** `lab/evidencias/parte1.txt` y `lab/evidencias/parte1_networksettings.json`.

> 📷 **[CAPTURA 1a]** secciones «1.2 a) Vista desde DENTRO» y «1.2 b) Vista desde el HOST».

| Observación | Dentro del contenedor | Desde el host |
|---|---|---|
| PID del proceso `python -c "...sleep(3600)"` | **1** | **6017** (`docker inspect -f '{{.State.Pid}}'`) |
| PIDs visibles | 1 y los del propio `docker exec` | todos los del sistema |
| Namespace PID (`readlink /proc/<pid>/ns/pid`) | `pid:[4026532265]` | `pid:[4026531836]` |
| `lsns -p 6017` | namespaces propios `mnt`, `uts`, `ipc`, `pid`, `net` | — |
| Sistema operativo (`/etc/os-release`) | Debian GNU/Linux 13 (trixie) | el del host |
| `hostname` | ID corto del contenedor | el del host |

**Conclusión:** es **un único proceso** en el kernel del host con dos identidades. El PID 1
dentro del contenedor y el PID 6017 en el host son la misma tarea; lo único que cambia es
el namespace desde el que se observa. Los inodos distintos del namespace PID prueban que
el aislamiento es efectivo. `lsns` muestra además que `time`, `cgroup` y `user` son los
mismos del host: Docker no aísla esos por defecto.

> 📷 **[CAPTURA 1b]** sección «1.3 IP virtual y red del contenedor».

Extracto de `NetworkSettings` (el JSON completo está en `parte1_networksettings.json`):

```json
"Networks": {
  "bridge": {
    "Gateway": "172.17.0.1",
    "IPAddress": "172.17.0.2",
    "IPPrefixLen": 16
  }
}
```

El contenedor recibe una IP virtual (`172.17.0.2`) en la red `bridge` por defecto
(`172.17.0.0/16`), cuya puerta de enlace `172.17.0.1` es la interfaz `docker0` del host.
Esa IP existe solo dentro del namespace de red del contenedor: por eso en la Parte 3 los
servicios se buscan **por nombre**, no por IP.

---

## 2. Parte 1 — Cgroups y OOM Killer (entregable 2)

> 📷 **[CAPTURA 2]** sección «1.4 Cgroups y OOM Killer» completa.

| Prueba | Resultado |
|---|---|
| `memory_bomb.py` con `-m 100m --memory-swap 100m` | último mensaje `Reservados: 90 MB`; sobrevive **2,4 s** |
| `echo $?` | **137** |
| `docker inspect ... OOMKilled / ExitCode` | `OOMKilled=true ExitCode=137 Error=` |
| `dmesg` | `Memory cgroup out of memory: Killed process 4409 (python) ... anon-rss:101760kB` |
| Límite visto por el contenedor | `104857600` = exactamente 100 MiB (`memory.limit_in_bytes`, cgroup v1; en v2 es `memory.max`) |
| Repetición con `-m 512m` | llega a `Reservados: 500 MB`, sobrevive **10,8 s**, también 137 |

**Análisis (máx. 8 líneas).** 137 = 128 + 9: el proceso murió por SIGKILL. No es un error
de Python sino un veredicto del kernel: el cgroup del contenedor agotó sus 100 MiB
(`CONSTRAINT_MEMCG`; la máquina tenía 14 GiB libres), el OOM killer eligió la víctima y le
envió SIGKILL, una señal que no se puede capturar, ignorar ni diferir. Python no vuelve a
ejecutar ni una instrucción: no hay `MemoryError`, traceback, `finally` ni flush de buffers,
y por eso el log termina en un «Reservados». En plena ingesta, lo que estuviera en buffer se
perdería. Con 512 MB vive 4,5 veces más: el límite es configuración, no naturaleza del programa.

---

## 3. Parte 2 — Dockerfile multi-etapa y `.dockerignore` (entregable 3)

Los archivos completos y comentados están en el **Anexo A** (`Dockerfile`) y el
**Anexo B** (`.dockerignore`). Las decisiones, en orden de importancia:

| Decisión | Por qué |
|---|---|
| Dos etapas: `builder` (venv + dependencias) y `runtime` (solo lo necesario) | Lo que se instale para *construir* no viaja a la imagen final |
| `requirements.txt` se copia **antes** que `src/` | La capa del `pip install` queda en caché: cambiar código no reinstala dependencias |
| venv creado con `--without-pip` | El venv no carga su propia copia de pip (~15 MB) que en ejecución nadie usa |
| `tini` como `ENTRYPOINT`, `CMD` en forma exec | El PID 1 recibe y reenvía SIGTERM, y recoge los zombies de los N workers |
| Usuario `appuser` con UID/GID fijos **10001** | No corre como root; el UID fijo permite dar permisos al bind mount del host |
| Código propiedad de **root**, solo `/app/data` es de `appuser` | El proceso puede leer su código pero no modificarlo |
| `PYTHONUNBUFFERED`, `PYTHONDONTWRITEBYTECODE`, `PYTHONFAULTHANDLER` | Logs en vivo; sin `.pyc` (raíz de solo lectura viable); traza ante fallos nativos |
| **Sin** `build-essential` en el builder | `requirements.txt` está vacío (solo biblioteca estándar): instalarlo alargaría el build sin cambiar la imagen. Queda comentado dónde va si se agrega una dependencia con extensiones en C |

**Efecto del `.dockerignore`** (sección «2.1» de `parte2.txt`), con el dataset de 1,8 GB
ya generado en `data/raw`:

| Build de `Dockerfile.v0` (`COPY . .`) | Contexto transferido | Imagen resultante |
|---|---|---|
| **Sin** `.dockerignore` | **1,89 GB** en 10,8 s | **3,57 GB** (¡el dataset queda dentro de la imagen!) |
| **Con** `.dockerignore` | **271 kB** | 1,61 GB |

Hallazgo: con el Dockerfile v2 el contexto transferido es de pocos bytes aun sin
`.dockerignore`, porque BuildKit solo envía las rutas que nombran los `COPY`
(`requirements.txt` y `src/`). El `.dockerignore` sigue siendo necesario como defensa: basta
que alguien agregue un `COPY . .` —o construya con el builder clásico, que siempre envía
todo— para volver a meter 1,9 GB de datos (y el `.env`) en la imagen.

---

## 4. Parte 2 — Tabla comparativa con mediciones propias (entregable 4)

> 📷 **[CAPTURA 4]** sección «2.5 Tabla comparativa» de `parte2.txt`.

| Versión | Estrategia | Tamaño final | Build en frío | Rebuild tras 1 línea |
|---|---|---|---|---|
| v0 | `python:3.12` + `COPY . .` + root | **1,61 GB** | 2,8 s | 2,7 s (sin caché útil) |
| v1 | `python:3.12-slim`, una etapa, requirements primero | 178 MB | 2,2 s | 0,4 s |
| v2 | Multi-etapa + venv + tini + usuario 10001 | **179 MB** | 4,4 s¹ | 1,0 s |
| Δ v0→v2 | Reducción obtenida | **−89 %** | — | **−63 %** |

¹ En el entorno de medición los contenedores no tenían salida a los repositorios de
Debian, así que `tini` se copió del binario estático que trae Docker (`docker-init`, que es
tini 0.19.0) en lugar de instalarse con `apt-get`. Con acceso a internet el build en frío
de v2 suma el `apt-get update && install tini` (del orden de 10 a 30 s según la red); el
tamaño final prácticamente no cambia.

**Lectura de la tabla.**

- **El tamaño lo decide la imagen base, no las etapas.** El salto de 1,61 GB a 179 MB viene de
  pasar de `python:3.12` a `python:3.12-slim`. Como este proyecto no tiene dependencias
  compiladas, v1 y v2 pesan casi lo mismo: v2 agrega tini (~1 MB) y el usuario. La ventaja
  del multi-etapa aparece en cuanto una dependencia necesite `gcc`: en una sola etapa el
  toolchain (cientos de MB) quedaría en la imagen final; en v2 se queda en el builder.
- **La caché funciona en v1 y v2 y no en v0.** En el rebuild de v2, `parte2.txt` muestra
  `CACHED` en `COPY requirements.txt` y en `RUN pip ... install`: solo se rehízo la capa
  `COPY src/`. En v0, el `COPY . .` cambia con cualquier línea y arrastra al
  `pip install` que viene después. Con `requirements.txt` vacío esa reinstalación cuesta
  poco (2,7 s); con dependencias reales como las que asume la guía serían minutos en cada
  cambio de código.
- **Los tiempos absolutos son chicos** porque las imágenes base ya estaban descargadas y
  no hay dependencias que instalar. Lo que se compara es la estructura, y la tendencia
  (rebuild v2 ≪ rebuild v0) es la que predice la teoría.

---

## 5. Parte 2 — Evidencia del hardening (entregable 5)

> 📷 **[CAPTURA 5a]** sección «2.4 Hardening» de `parte2.txt`.

```
$ docker run --rm --entrypoint sh proyecto:v2 -c 'id && which python'
uid=10001(appuser) gid=10001(appgroup) groups=10001(appgroup)
/opt/venv/bin/python

$ docker run --rm --entrypoint sh proyecto:v0 -c 'id && which python'
uid=0(root) gid=0(root) groups=0(root)
/usr/local/bin/python

$ docker run --rm --entrypoint sh proyecto:v2 -c 'ls -ld /app/src /app/data; touch /app/src/x'
drwxr-xr-x 2 appuser appgroup 4096 ... /app/data
drwxr-xr-x 3 root    root     4096 ... /app/src
touch: cannot touch '/app/src/x': Permission denied
```

> 📷 **[CAPTURA 5b]** sección «2.4 SIGTERM en el PID 1» de `parte2.txt`.

| Contenedor | PID 1 (`/proc/1/cmdline`) | `time docker stop` | ExitCode |
|---|---|---|---|
| `sin-init` (v0) | `/bin/sh -c python src/receptor_tcp.py` | **10,2 s** | **137** |
| `con-init` (v2) | `/usr/bin/tini -- python -u src/receptor_tcp.py` | **0,2 s** | **143** |

**Por qué.** En v0 el `CMD` en forma shell hace que el PID 1 sea `/bin/sh` (en Debian, `dash`
no hace `exec` del comando: se verificó que el shell sigue siendo el PID 1). El kernel no
aplica la acción por defecto de SIGTERM al PID 1 de un namespace y `sh` no instala
manejador ni reenvía la señal, así que el SIGTERM de `docker stop` se pierde: Docker espera
los 10 s de gracia y termina con SIGKILL (137). El receptor muere sin hacer flush. El propio
linter de Docker lo advierte sobre `Dockerfile.v0` (`docker build --check`): *«JSON arguments
recommended for CMD to prevent unintended behavior related to OS signals»*. En v2,
`tini` es el PID 1, reenvía SIGTERM a Python, y el receptor la atiende:

```python
# src/receptor_tcp.py (extracto)
for sig in (signal.SIGTERM, signal.SIGINT):
    loop.add_signal_handler(sig, _al_recibir, sig)   # dentro del bucle asyncio
...
log.info("%s recibido: cerrando sockets y haciendo flush del .jsonl", nombre)
server.close()                  # deja de aceptar conexiones
for t in activas: t.cancel()    # cada conexion escribe sus lineas completas,
                                # hace flush + fsync y cierra su archivo
return 128 + recibida[0]        # 143: "termine por SIGTERM, despues de vaciar"
```

Se usa `loop.add_signal_handler` y no `signal.signal` porque el manejador corre como una
llamada más del bucle, entre dos `await`, con el estado consistente. El receptor sale con
**143 a propósito** (convención 128 + nº de señal): así el código conserva el significado de
«terminado por SIGTERM», y el log `apagado limpio` certifica que fue *después* del flush.
Probado también en plena ingesta: con SIGTERM a los 3 s, los cuatro archivos quedaron con
1.647.446 líneas, **todas válidas** (ninguna cortada), el manifiesto los marca como
`interrumpido` y el simulador sale con código 1 porque los acuses no llegaron.

---

## 6. Parte 3 — `docker-compose.yml` parametrizado y `.env` (entregable 6)

Archivos completos en el **Anexo C** (`docker-compose.yml`) y el **Anexo D**
(`.env.example`, que se copia a `.env`; el `.env` está en `.gitignore`).

| Requisito | Cómo se cumple |
|---|---|
| Dos servicios que se comunican por nombre | `simulador-puerto` → `TCP_HOST=ingestor-tcp`, resuelto por el DNS interno (`172.18.0.2`) |
| Red privada | `red-datos-lab`, driver `bridge`, separada de la `bridge` por defecto |
| Receptor alcanzable | `BIND_HOST: 0.0.0.0` (con `127.0.0.1` sería inalcanzable desde el otro contenedor) |
| El simulador no emite antes de tiempo | `depends_on: condition: service_healthy` + `healthcheck` que abre el puerto |
| Persistencia en el host | bind mount `${HOST_DATA_DIR}:${DATA_DIR}` → `./data/raw` |
| Parametrización | todo sale del `.env`; cada variable tiene un valor por defecto `${VAR:-...}` |
| Límites | `mem_limit` por servicio; `stop_grace_period: 30s` para el flush final |

Decisiones propias, más allá de la guía:

- **Sin `init: true`.** La imagen ya trae `tini` como `ENTRYPOINT`; `init: true` pondría
  un segundo init (`docker-init`) delante, y tini avisa que no es PID 1 ni *subreaper*.
- **Puerto publicado en `127.0.0.1`**, no en todas las interfaces: sirve para depurar desde
  el host sin exponer el ingestor a la red local.
- **Endurecimiento adicional** común a ambos servicios (ancla `x-endurecido`): raíz de solo
  lectura (`read_only: true` + `tmpfs: /tmp`), `cap_drop: [ALL]` y
  `no-new-privileges:true`. Funcionan porque el único lugar donde se escribe es el volumen.
- `N_PROCESOS=4` porque el equipo de medición tiene 4 núcleos.

> 📷 **[CAPTURA 6]** `docker compose config` (sección «3.4» de `parte3.txt`) y
> `docker compose ps` con el ingestor `healthy`.

---

## 7. Parte 3 — Evidencia de persistencia de los 10 millones de eventos (entregable 7)

> 📷 **[CAPTURA 7a]** red privada y resolución por nombre (`parte3.txt`, sección 3.4):
> ```
> simulador-puerto -> 172.18.0.3/16
> ingestor-tcp -> 172.18.0.2/16
> $ docker compose exec simulador-puerto python -c "import socket; print(socket.gethostbyname('ingestor-tcp'))"
> 172.18.0.2
> ```

> 📷 **[CAPTURA 7b]** crecimiento en vivo y conteo final:
> ```
> $ docker compose ps -a
> ingestor-tcp       ...  Up 31 seconds (healthy)    127.0.0.1:9009->9009/tcp
> simulador-puerto   ...  Exited (0) 4 seconds ago
>
> $ wc -l data/raw/*.jsonl
>    2513970 data/raw/part-000.jsonl
>    2513970 data/raw/part-001.jsonl
>    2513970 data/raw/part-002.jsonl
>    2458104 data/raw/part-003.jsonl
>   10000014 total
>
> $ du -sh data/raw/
> 1.8G    data/raw/
> ```

> 📷 **[CAPTURA 7c]** la prueba definitiva:
> ```
> $ docker compose stop
> $ docker inspect ingestor-tcp --format 'ingestor-tcp ExitCode={{.State.ExitCode}}'
> ingestor-tcp ExitCode=143
> $ docker compose down
>  Container simulador-puerto Removed
>  Container ingestor-tcp Removed
>  Network red-datos-lab Removed
> $ docker compose ps -a
> NAME      IMAGE     COMMAND   SERVICE   CREATED   STATUS    PORTS
> $ ls -lh data/raw/
> -rw-r--r-- 1 10001 10001 1.3K manifiesto_receptor.json
> -rw-r--r-- 1 10001 10001 451M part-000.jsonl
> -rw-r--r-- 1 10001 10001 451M part-001.jsonl
> -rw-r--r-- 1 10001 10001 451M part-002.jsonl
> -rw-r--r-- 1 10001 10001 441M part-003.jsonl
> $ wc -l data/raw/*.jsonl | tail -n 1
>   10000014 total
> ```

**¿Por qué 10.000.014 y no 10.000.000?** Desde la Fase 1, `TOTAL_EVENTOS` es un **piso**: los
179 puntos de medición reportan por *ticks* completos de 15 s, y ⌈10.000.000 / 179⌉ = 55.866
ticks × 179 = 10.000.014. Cortar el último tick dejaría series de distinto largo justo en
el borde del dataset. Se cumple el mínimo de 10 millones y cada sensor cubre la misma
ventana de 9,7 días simulados.

**Integridad.** Además del conteo: (1) cada worker recibió el acuse del receptor con su
conteo exacto después del `fsync` (log `cerrado: 2513970/2513970 eventos ... (completo)`);
(2) `manifiesto_receptor.json` registra `total_recibido: 10000014` y
`archivos_completos: 4`; (3) `python3 -m bench.validar data/raw --profundo` recorrió las
10.000.014 líneas y validó el esquema campo a campo: `OK: dataset valido`. La corrida
completa tardó ~20 s (≈490.000 eventos/s, ≈92 MB/s) con 70 MiB de RAM en el simulador y
menos de 50 MiB en el ingestor.

---

## 8. Conclusión (entregable 8)

**Rendimiento.** Contenerizar no costó rendimiento: 10.000.014 eventos por TCP entre dos
contenedores en ~20 s (≈490.000 ev/s, 92 MB/s), el orden de la Fase 1 escribiendo directo a
disco. La imagen bajó de 1,61 GB a 179 MB (−89 %), la caché evita reinstalar dependencias al
cambiar código y el `.dockerignore` evitó enviar 1,89 GB de contexto. **Seguridad.** Los
procesos corren como UID 10001, sin capacidades ni escalada de privilegios, con la raíz de
solo lectura, sin poder modificar su código y en una red privada; el puerto solo se publica
en el loopback. El OOM killer mostró que un SIGKILL pierde lo que hay en buffer: por eso el
PID 1 es tini, el receptor atiende SIGTERM (0,2 s y 143 contra 10,2 s y 137) y el acuse tras
`fsync` hace que el simulador solo informe éxito con los datos en disco. **Límite del
ingestor: 256 MiB.** Su RSS medido es ≈ 28 MiB + 4,3 MiB por conexión (46 MiB con 4 workers,
96 MiB con 16) y no depende del total, porque trabaja en streaming con buffers acotados; el
resto de lo que marca `docker stats` es caché de páginas que el kernel recupera. Con 48 MiB
aún funciona; con 32 MiB el kernel lo mata y el simulador falla. 256 MiB da 5× de margen con
4 workers y 2,5× con 16 sin dejar de proteger al host; 1 GiB funciona pero no aporta velocidad.

**Respaldo de la recomendación** (`lab/limite_ingestor.sh`, 2.000.146 eventos por corrida;
la memoria del receptor no depende del total):

| `MEM_INGESTOR` | Workers | Resultado | Pico RSS del receptor (VmHWM) |
|---|---|---|---|
| 1g | 4 | OK | 46,2 MiB |
| 256m | 4 | OK | 46,2 MiB |
| 64m | 4 | OK | 45,4 MiB |
| 48m | 4 | OK | 45,4 MiB |
| 32m | 4 | **Falla**: OOM kill, Compose lo reinicia, 21.234 eventos en disco, simulador sale con 1 | — |
| 1g | 8 | OK | 64,2 MiB |
| 128m | 16 | OK | 96,6 MiB |

---

## Cómo reproducir

```bash
python -m bench.test_formato           # tests, incluidos los del receptor TCP
bash lab/parte1.sh                     # entregables 1 y 2
bash lab/parte2.sh                     # entregables 3, 4 y 5 (restaura los archivos que toca)
bash lab/parte3.sh --limpiar           # entregables 6 y 7 (borra un dataset anterior)
bash lab/limite_ingestor.sh            # tabla de la conclusión
```

## Diagnóstico rápido (problemas encontrados o previstos)

| Síntoma | Causa | Solución |
|---|---|---|
| `Connection refused` desde el simulador | el receptor escucha en `127.0.0.1` | `BIND_HOST=0.0.0.0` (ya es el valor por defecto de la imagen) |
| el simulador apunta a `localhost` | dentro de Compose el destino es el nombre del servicio | `TCP_HOST=ingestor-tcp` |
| `sin permiso de escritura en /app/data (uid 10001)` | el bind mount pertenece a otro usuario | `sudo chown -R 10001:10001 data/raw` |
| el ingestor muere con 137 y se reinicia | `mem_limit` por debajo de su RSS (~46 MiB con 4 workers) | subir `MEM_INGESTOR` (recomendado 256m) |
| el simulador sale con 1 y `acuse ... conteo distinto` | el receptor murió o se detuvo durante la ingesta | revisar `docker compose logs ingestor-tcp`; regenerar con `bash lab/parte3.sh --limpiar` |
| `wc -l` cuenta más de lo esperado | quedaron `part-*.jsonl` de una corrida con más workers | el receptor lo avisa en su log; borrar antes de regenerar |
| no se pueden borrar los `.jsonl` del host | pertenecen al UID 10001 | `sudo rm data/raw/*.jsonl` |

---

## Anexo A — `Dockerfile`

```dockerfile
# syntax=docker/dockerfile:1
# ============================================================================
#  v2 - Imagen multi-etapa, endurecida, del TPC Sitio 3.
#
#  Una sola imagen para los dos servicios de docker-compose.yml:
#    ingestor-tcp      python -u src/receptor_tcp.py          (CMD por defecto)
#    simulador-puerto  python -u -m src.main --arch tcp ...   (command: en Compose)
#
#  Construir:  docker build -t proyecto:v2 .
# ============================================================================


# ============================================================================
#  ETAPA 1 - builder: prepara el entorno virtual con las dependencias
# ============================================================================
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Si una dependencia de requirements.txt necesitara compilar extensiones en C
# (numpy desde fuente, psycopg2, etc.), el toolchain se instala AQUI y solo
# aqui, porque esta etapa se descarta:
#   RUN apt-get update && apt-get install -y --no-install-recommends \
#           build-essential gcc && rm -rf /var/lib/apt/lists/*
# Hoy requirements.txt esta vacio (solo biblioteca estandar), asi que
# instalarlo solo alargaria el build sin cambiar la imagen final.

# Entorno virtual aislado: es lo UNICO que viaja de esta etapa a la final.
# --without-pip: el venv no lleva su propia copia de pip (~15 MB) que en
# ejecucion nadie usa; las dependencias se instalan con el pip de la imagen
# base apuntando al interprete del venv (--python).
RUN python -m venv --without-pip /opt/venv

WORKDIR /app

# CACHE: requirements.txt se copia ANTES que el codigo fuente. Mientras este
# archivo no cambie, Docker reutiliza la capa del pip install aunque cambie
# todo src/: reconstruir tras editar una linea de codigo no reinstala nada.
COPY requirements.txt .
RUN pip --python /opt/venv/bin/python install --no-cache-dir -r requirements.txt


# ============================================================================
#  ETAPA 2 - runtime: minima, sin toolchain, sin privilegios
# ============================================================================
FROM python:3.12-slim AS runtime

# PYTHONUNBUFFERED    stdout/stderr sin buffer: `docker logs` muestra el
#                     progreso de la ingesta en vivo y no se pierde si el
#                     proceso muere.
# PYTHONDONTWRITEBYTECODE  no escribe .pyc: el codigo pertenece a root y es
#                     de solo lectura para appuser, y el contenedor puede
#                     correr con el sistema de archivos en solo lectura.
# PYTHONFAULTHANDLER  traza de Python ante SIGSEGV/SIGABRT: distingue un
#                     fallo del codigo de un SIGKILL del kernel (que no deja
#                     traza porque no se puede atrapar).
# PATH                python y pip resuelven al venv copiado del builder,
#                     sin tener que activarlo.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    PATH="/opt/venv/bin:$PATH" \
    BIND_HOST=0.0.0.0 \
    TCP_PORT=9009 \
    DATA_DIR=/app/data

# tini: init minimo para el PID 1. El kernel NO aplica la accion por defecto
# de SIGTERM al PID 1 de un namespace; tini si recibe la senal, la reenvia a
# Python y ademas recoge los procesos zombie (el simulador crea N hijos).
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini \
 && rm -rf /var/lib/apt/lists/*

# Usuario sin privilegios con UID/GID FIJOS: el bind mount del host tiene que
# pertenecer a este mismo UID (sudo chown -R 10001:10001 data/raw).
RUN groupadd --gid 10001 appgroup \
 && useradd --uid 10001 --gid appgroup --no-create-home \
            --home-dir /nonexistent --shell /usr/sbin/nologin appuser

WORKDIR /app

# Solo el venv ya construido: el builder y todo lo que instalo se quedan atras.
COPY --from=builder /opt/venv /opt/venv

# El codigo queda como propiedad de root (sin --chown): appuser puede leerlo y
# ejecutarlo pero no modificarlo. Si el proceso fuera comprometido, no podria
# reescribir su propio codigo.
COPY src/ ./src/

# El unico directorio donde appuser puede escribir: el punto de montaje de
# los datos.
RUN mkdir -p /app/data && chown appuser:appgroup /app/data

USER appuser
EXPOSE 9009

# Forma exec (JSON): sin /bin/sh de por medio. tini es el PID 1 y Python su
# hijo directo, asi que el SIGTERM de `docker stop` llega a quien corresponde.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-u", "src/receptor_tcp.py"]
```

## Anexo B — `.dockerignore`

```gitignore
# ----------------------------------------------------------------------------
# Lo que NO se envia al daemon de Docker como contexto de build.
#
# Sin este archivo, un `COPY . .` (Dockerfile.v0) envia al daemon el
# directorio completo, incluidos los ~1,9 GB de data/raw y el historial de
# git: medido, 1,89 GB y 12 s de "transferring context" contra 271 kB con el.
# Y esos 1,9 GB terminan DENTRO de la imagen.
#
# El Dockerfile v2 copia solo requirements.txt y src/, y BuildKit ya
# transfiere nada mas que lo que los COPY nombran. El .dockerignore sigue
# siendo la defensa para el dia en que alguien agregue un `COPY . .` o
# construya con el builder clasico, que siempre envia todo.
# ----------------------------------------------------------------------------

# Control de versiones
.git
.gitignore

# Artefactos de Python
__pycache__/
*.py[cod]
.venv/
venv/
.pytest_cache/
*.prof

# Datos: el dataset crudo, la muestra y cualquier .jsonl suelto
data/
*.jsonl
*.log

# Configuracion local y secretos: nunca dentro de una imagen
.env
.env.*

# Lo que no se ejecuta dentro del contenedor
tests/
bench/
docs/
lab/
*.md
Dockerfile*
docker-compose*.yml
.dockerignore
```

## Anexo C — `docker-compose.yml`

```yaml
# ============================================================================
#  TPC Sitio 3 - simulador multiproceso + receptor TCP asincrono
#
#    cp .env.example .env              # parametros (el .env no se versiona)
#    mkdir -p data/raw && sudo chown -R 10001:10001 data/raw
#    docker compose up -d --build
#    docker compose logs -f
#
#  Todos los valores salen del .env. Los que van con ":-" tienen un valor por
#  defecto para que `docker compose config` funcione aun sin .env.
# ============================================================================
name: ${COMPOSE_PROJECT_NAME:-lab-bigdata}

# Endurecimiento comun a los dos servicios (ancla YAML, se fusiona abajo).
x-endurecido: &endurecido
  # Sistema de archivos raiz de solo lectura: el unico lugar escribible del
  # ingestor es el volumen de datos; el simulador no escribe en disco.
  read_only: true
  tmpfs:
    - /tmp
  # Sin capacidades de Linux: ninguno de los dos servicios necesita abrir
  # puertos < 1024, cambiar de usuario ni tocar la red del host.
  cap_drop: [ALL]
  # Un proceso no puede ganar privilegios nuevos (setuid, etc.).
  security_opt:
    - no-new-privileges:true

services:

  ingestor-tcp:
    <<: *endurecido
    build:
      context: .
      target: runtime            # etapa final del Dockerfile multi-etapa
    image: proyecto/ingestor:v2
    container_name: ingestor-tcp
    # PID 1 correcto: lo resuelve el ENTRYPOINT de la imagen (tini). NO se
    # agrega `init: true`, que pondria un SEGUNDO init (docker-init) delante
    # de tini; tini avisa entonces que no es PID 1 ni subreaper.
    command: ["python", "-u", "src/receptor_tcp.py"]
    environment:
      BIND_HOST: 0.0.0.0         # CLAVE: 127.0.0.1 seria inalcanzable desde la red
      TCP_PORT: ${TCP_PORT:-9009}
      DATA_DIR: ${DATA_DIR:-/app/data}
      REPORTE_S: ${REPORTE_S:-5}
    ports:
      # Solo para depurar desde el host (p. ej. `nc 127.0.0.1 9009`). Se
      # publica en el loopback del host y no en 0.0.0.0: el ingestor no
      # queda expuesto a la red local.
      - "127.0.0.1:${TCP_PORT:-9009}:${TCP_PORT:-9009}"
    volumes:
      # Bind mount -> los .jsonl viven en una ruta concreta del host y
      # sobreviven a `docker compose down`.
      - ${HOST_DATA_DIR:-./data/raw}:${DATA_DIR:-/app/data}
    networks: [red-datos]
    mem_limit: ${MEM_INGESTOR:-1g}
    stop_grace_period: 30s       # tiempo para flush + fsync antes del SIGKILL
    restart: unless-stopped
    healthcheck:
      # Verifica desde dentro que el puerto ya acepta conexiones. El receptor
      # descarta en silencio una conexion que no envia datos.
      test: >-
        python -c "import socket,os;
        socket.create_connection(('127.0.0.1', int(os.environ['TCP_PORT'])), 3).close()"
      interval: 5s
      timeout: 5s
      retries: 5
      start_period: 5s

  simulador-puerto:
    <<: *endurecido
    build:
      context: .
      target: runtime
    image: proyecto/simulador:v2
    container_name: simulador-puerto
    # --arch tcp: cada worker abre su propia conexion con el ingestor.
    # --bench-csv "": el contenedor no tiene bench/mediciones.csv (y su raiz
    # es de solo lectura); el registro de la corrida lo deja el receptor en
    # data/raw/manifiesto_receptor.json.
    command: ["python", "-u", "-m", "src.main", "--arch", "tcp", "--bench-csv", ""]
    environment:
      TCP_HOST: ${TCP_HOST:-ingestor-tcp}    # resuelve por el DNS interno de Docker
      TCP_PORT: ${TCP_PORT:-9009}
      TOTAL_EVENTOS: ${TOTAL_EVENTOS:-10000000}
      N_PROCESOS: ${N_PROCESOS:-4}
      BATCH_SIZE: ${BATCH_SIZE:-50000}
    depends_on:
      ingestor-tcp:
        condition: service_healthy   # no emite hasta que el puerto acepta
    networks: [red-datos]
    mem_limit: ${MEM_SIMULADOR:-512m}
    restart: "no"                    # es un job: termina y no se reinicia

networks:
  red-datos:
    name: red-datos-lab
    driver: bridge                   # red privada, aislada de la bridge por defecto
```

## Anexo D — `.env.example (se copia a .env)`

```bash
# ----------------------------------------------------------------------------
# Parametros de docker-compose.yml. Copiar a .env antes de levantar:
#     cp .env.example .env
# El .env esta en .gitignore. Estos son valores de ejemplo: no hay secretos.
# ----------------------------------------------------------------------------
COMPOSE_PROJECT_NAME=lab-bigdata

# Red y puertos
TCP_HOST=ingestor-tcp        # nombre DNS del servicio receptor, NO localhost
TCP_PORT=9009

# Carga de trabajo
TOTAL_EVENTOS=10000000       # piso: se redondea al tick completo (10.000.014)
N_PROCESOS=4
BATCH_SIZE=50000

# Almacenamiento
HOST_DATA_DIR=./data/raw     # carpeta del host (bind mount)
DATA_DIR=/app/data           # donde la ve el contenedor

# Limites de recursos
MEM_INGESTOR=1g
MEM_SIMULADOR=512m

# Segundos entre lineas de progreso del receptor en `docker compose logs`
REPORTE_S=5
```
