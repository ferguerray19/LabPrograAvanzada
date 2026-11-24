"""Genera Informe_Lab2_Docker.pdf a partir de lab/evidencias/.

    python docs/informe_pdf/build_informe.py [ruta_salida.pdf]

Reglas que aplica el propio script:
  * Toda cifra del texto se EXTRAE de un archivo de lab/evidencias/ (no hay
    numeros medidos escritos a mano). Si un patron no aparece, el build falla.
  * Cada bloque de terminal cita su archivo y rango de lineas, y se verifica
    que cada linea del bloque exista en ese archivo.
  * Las afirmaciones cualitativas (137 frente a 143, UID 10001, 10 M eventos,
    plazo de docker stop estable...) se comprueban con `verificar` o eligen
    la redaccion segun el dato; si algo no calza, el build se detiene para
    revisarlo en vez de publicar un texto que no corresponde a la medicion.
  * Los controles de proceso (lineas de la conclusion, del analisis del OOM)
    se informan por consola, nunca dentro del PDF.
"""
import csv
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pdfkit import *  # noqa: E402,F401,F403
from pdfkit import _esc  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import PageBreak, SimpleDocTemplate, Spacer  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
EVD = REPO / "lab" / "evidencias"
SALIDA = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO.parent / "Informe_Lab2_Docker.pdf"
AVISOS = []


def verificar(cond, mensaje):
    if not cond:
        raise SystemExit(f"VERIFICACION FALLIDA: {mensaje}")


def ev(nombre):
    return Evidencia(EVD / nombre, REPO)


e1, e2, e3 = ev("parte1.txt"), ev("parte2.txt"), ev("parte3.txt")
eb, ep, el = ev("baseline_nativo.txt"), ev("permisos_linux.txt"), ev("limite_ingestor.txt")
er = ev("rendimiento_contenedor.txt")
TABLA2 = (EVD / "parte2_tabla.md").read_text(encoding="utf-8")


def cmds(texto, *prefijos, max_lineas=None):
    """Bloques '$ comando + salida' cuyo comando empieza con alguno de los prefijos."""
    out = []
    for b in re.split(r"\n(?=\$ )", "\n" + texto):
        b = b.strip("\n")
        if b.startswith("$ ") and any(b[2:].startswith(p) for p in prefijos):
            ls = b.splitlines()
            if max_lineas and len(ls) > max_lineas:
                ls = ls[:max_lineas] + ["[...]"]
            out.append("\n".join(ls))
    verificar(out, f"no hay comandos {prefijos}")
    return "\n\n".join(out)


def definicion(script, *nombres):
    """Bloque con la linea real del script que define cada variable usada en
    una captura, citando el script y su numero de linea."""
    lineas = (REPO / script).read_text(encoding="utf-8").split("\n")
    out, nums = [], []
    for n in nombres:
        k = next((i for i, l in enumerate(lineas) if re.match(rf"^\s*{n}=", l)), None)
        verificar(k is not None, f"{script} no define {n}")
        out.append(lineas[k].strip())
        nums.append(str(k + 1))
    pie = f"Definición en {script}, " + ("línea " if len(nums) == 1 else "líneas ") + lista_es(nums)
    return codigo("\n".join(out), pie)


def sin(texto, patron):
    return "\n".join(l for l in texto.splitlines() if not re.search(patron, l))


def tam(s):
    """'1.61GB' -> '1,61 GB' (solo formato)."""
    m = re.fullmatch(r"([\d.]+)\s*([kKMG]?B)", s.strip())
    return f"{m.group(1).replace('.', ',')} {m.group(2)}" if m else s


def a_mb(s):
    m = re.fullmatch(r"([\d.]+)\s*([kKMG]?B)", s.strip())
    return float(m.group(1)) * {"GB": 1000, "MB": 1, "kB": 0.001, "KB": 0.001, "B": 1e-6}[m.group(2)]


def seg(s):
    return str(s).replace(".", ",")


def filas_md(texto, cabecera):
    """Filas de la tabla markdown de `texto` cuya cabecera empieza con `cabecera`."""
    lineas = texto.splitlines()
    i = next(k for k, l in enumerate(lineas) if l.startswith("| " + cabecera))
    filas = []
    for l in lineas[i + 2:]:
        if not l.startswith("|"):
            break
        filas.append([c.strip() for c in l.strip().strip("|").split("|")])
    return filas


def signo(s):
    """'-20 %' -> '−20 %' (signo menos tipografico)."""
    return re.sub(r"^-", "−", s.strip())


def dec(s):
    """Decimales con coma en textos propios del informe: '1.1 s' -> '1,1 s'."""
    return re.sub(r"(\d)\.(\d)", lambda m: m.group(1) + "," + m.group(2), s)


def serie(vals, unidad="s"):
    """'3,02 s en las tres' si todos son iguales; si no, 'a, b y c s'."""
    vals = [seg(v) for v in vals]
    if len(set(vals)) == 1:
        return f"{vals[0]} {unidad} cada vez" if len(vals) > 1 else f"{vals[0]} {unidad}"
    return lista_es(vals) + f" {unidad}"


def lista_es(xs):
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " y " + xs[-1]


# Tildes de los textos que generan los scripts (sin tildes a proposito) y que
# el informe muestra como encabezados o celdas propias, no como terminal.
TILDES = {"Reduccion obtenida": "Reducción obtenida", "una etapa, requirements primero": "una etapa, requirements primero"}


def tildes(s):
    for a, b in TILDES.items():
        s = s.replace(a, b)
    return s


# =========================================================================
#  Datos extraidos de la evidencia
# =========================================================================
# --- entorno
ENGINE = e1.buscar(r"^Cliente \S+ / Engine (\S+)")
PLATAFORMA = e1.buscar(r"^Cliente \S+ / Engine \S+ / (.+)$")
COMPOSE = e1.buscar(r"^Docker Compose version (\S+)")
KERNEL, NCPU, RAM_B, CGV = re.search(r"kernel (\S+) \| (\d+) CPU \| (\d+) B RAM \| cgroup v(\d)", e1.texto).groups()
for e in (e2, e3, ep, el, er):
    verificar(f"Docker version {ENGINE}" in e.texto.split("\n")[0] or f"Engine {ENGINE}" in e.texto,
              f"{e.rel} no se tomo con Engine {ENGINE}")

# --- parte 1
PID = e1.buscar(r"^\$ docker inspect -f '\{\{\.State\.Pid\}\}' lab-ns\n(\d+)")
NSPID = e1.buscar(r"^NSpid:\s+(\d+\s+\d+)")
verificar(NSPID.split()[0] == PID and NSPID.split()[1] == "1", "NSpid no es '<PID> 1'")
NS_C = e1.buscar(r"^contenedor: (pid:\[\d+\])")
NS_H = e1.buscar(r"^host:\s+(pid:\[\d+\])")
NS_DENTRO = e1.buscar(r"readlink /proc/1/ns/pid\n(pid:\[\d+\])")
verificar(NS_C == NS_DENTRO and NS_C != NS_H, "namespaces PID no calzan")
PIDS_VIS = ", ".join(sorted(e1.buscar(r"^PIDs visibles:\n(.+)$").split(), key=int))
LSNS = re.findall(r"^\s*(\d{9,})\s+(\w+)\s+\d+\s+(\d+)\s", e1.s("1.2 b)"), re.M)
NS_PROPIOS = [t for _, t, p in LSNS if p == PID]
NS_HOST = [t for _, t, p in LSNS if p != PID]
verificar(NS_HOST, "lsns no muestra namespaces compartidos con el host")
IP = e1.buscar(r'"IPAddress": "([\d.]+)"')
GW = e1.buscar(r'"Gateway": "([\d.]+)"')
PREF = e1.buscar(r'"IPPrefixLen": (\d+)')
SUBNET = e1.buscar(r'"Subnet":"([\d./]+)"')
DOCKER0 = e1.buscar(r"^\s+inet ([\d./]+) .*scope global docker0")
verificar(DOCKER0.split("/")[0] == GW, "docker0 no es la puerta de enlace del contenedor")
PING = e1.buscar(r"^(\d+ packets transmitted, \d+ packets received, \d+% packet loss)$")
verificar(PING.endswith(" 0% packet loss"), f"el ping al contenedor perdio paquetes: {PING}")
OOM_SEC = e1.s("1.4 Cgroups")
ULT100 = re.findall(r"^Reservados: (\d+) MB", OOM_SEC, re.M)[-1]
ECHO = e1.buscar(r"^\$ echo \$\?\n(\d+)")
OOMK = e1.buscar(r"^(OOMKilled=\S+ ExitCode=\d+ Error=.*)$")
verificar(ECHO == "137" and "OOMKilled=true ExitCode=137" in OOMK, "el OOM no dio 137/true")
# dmesg filtrado por el contenedor lab-oom: todas las lineas del kernel que se
# muestran tienen que ser de ESE contenedor, y la tabla cita el mismo PID.
CID, OOM_PID = re.search(r"^CID=([0-9a-f]{64})  OOM_PID=(\d+)$", OOM_SEC, re.M).groups()
DMESG = [l for l in OOM_SEC.splitlines() if l.startswith("[")]
verificar(DMESG and all(CID in l or f"process {OOM_PID} " in l for l in DMESG),
          "la captura del dmesg trae lineas de otro contenedor")
DM_PID, DM_RSS, DM_UID = re.search(r"Killed process (\d+) \(python\).*?anon-rss:(\d+)kB.*?UID:(\d+)", OOM_SEC).groups()
verificar(DM_PID == OOM_PID and DM_UID == "0", "el proceso muerto del dmesg no es el de lab-oom (UID 0)")
DM_CONS = "CONSTRAINT_MEMCG" in OOM_SEC
MEMMAX = e1.buscar(r"memory\.max\n(\d+)")
T100, T512 = re.search(r"Con 100 MB sobrevivio ([\d.]+) s; con 512 MB, ([\d.]+) s", e1.texto).groups()
ULT512 = re.findall(r"^Reservados: (\d+) MB", e1.s("1.4 Repeticion"), re.M)[-1]
verificar("OOMKilled=true ExitCode=137" in e1.s("1.4 Repeticion"), "512m no termino en OOM 137")

# --- parte 2
CTX = re.findall(r"transferring context: (\S+) ([\d.]+)s done", e2.s("2.1"))
IMG_CTX = re.findall(r"^tamano de la imagen resultante: (\S+)$", e2.s("2.1"), re.M)
verificar(len(CTX) == 2 and len(IMG_CTX) == 2, "falta la medicion de contexto")
T2 = filas_md(TABLA2, "Version")
V = {f[0]: f for f in T2}
REPS_TXT = re.search(r"Repeticiones \(s\): (.+?)\n(.+?)\n", TABLA2).group(0).strip()
STOPS = {f[0].split()[0]: [c[:-2] if c.endswith(" s") else c for c in f]
         for f in filas_md(TABLA2, "Prueba de docker stop")}
STOP_DEF = e2.buscar(r"^StopTimeout=(\S+)$")
UID_V2 = e2.buscar(r"^\$ docker run --rm --entrypoint sh proyecto:v2 -c 'id && which python'\n(.+)$")
verificar(UID_V2.startswith("uid=10001(appuser)"), "v2 no corre como 10001")
PID1_SIN = e2.buscar(r"docker exec sin-init cat /proc/1/cmdline.*\n(.+)$").strip()
PID1_CON = e2.buscar(r"docker exec con-init cat /proc/1/cmdline.*\n(.+)$").strip()
S10, C10 = STOPS["sin-init-10"], STOPS["con-init-10"]
verificar(STOPS["con-init"][3] == "143", f"con-init sin plazo no salio con 143: {STOPS['con-init']}")
verificar(S10[3] == "137" and C10[3] == "143", f"stop con 10 s no dio 137/143: {S10} {C10}")
# plazo real que aplico el daemon sin --stop-timeout (docker events)
EVT = e2.s("2.4 Plazo que aplica el daemon")
PLAZOS = [float(x) for x in re.findall(r"plazo SIGTERM->SIGKILL segun el daemon: ([\d.]+) s", EVT)]
T_DEFS = re.findall(r"time docker stop: ([\d.]+) s \| ExitCode=(\d+)", EVT)
PLAZO_ESTABLE = len(PLAZOS) == 3 and max(PLAZOS) - min(PLAZOS) <= 0.5
if not PLAZO_ESTABLE:
    AVISOS.append(f"I2: el plazo sin --stop-timeout no fue estable {PLAZOS}; se omite la corrida por defecto (opcion b)")
PASOS_V2 = e2.buscar(r"Tiempo de cada paso del rebuild de v2 \(repeticion 1[^\n]*\n((?:[^\n]+\n)+)", 1)
PASOS_T = [(float(t[:-1]), n.strip()) for t, n in re.findall(r"^([\d.]+s)\s+(.+)$", PASOS_V2, re.M)]
PASOS_CACHED = len(re.findall(r"^CACHED", PASOS_V2, re.M))
PARED_V2_R1 = e2.buscar(r"-t proyecto:v2 -f Dockerfile \.\s+# rebuild, repeticion 1\nreal ([\d.]+)s")
_META = sum(t for t, n in PASOS_T if n.startswith(("resolve image config", "[internal] load metadata")))
verificar(_META >= 0.5 * sum(t for t, _ in PASOS_T),
          "las consultas de metadatos ya no son la mayor parte del rebuild de v2: revisar el texto")
PIP_REPS = re.findall(r"repeticion (\d+):\s+v0 (\S+)\s+v1 (\S+)\s+v2 (\S+)", e2.texto)
verificar(PIP_REPS and all(v2 == "CACHED" and v1 == "CACHED" and v0 != "CACHED" for _, v0, v1, v2 in PIP_REPS),
          f"la capa pip no se comporta como se afirma: {PIP_REPS}")


def nombre_paso(n):
    """Nombre legible de un paso de BuildKit para la prosa."""
    tabla_n = [
        ("resolve image config for docker-image://docker.io/docker/dockerfile", f"resolver el frontend {M('dockerfile:1')}"),
        ("[internal] load metadata for docker.io/library/python:3.12-slim", f"leer los metadatos de {M('python:3.12-slim')}"),
        ("[internal] load metadata for docker.io/library/python:3.12", f"leer los metadatos de {M('python:3.12')}"),
        ("[runtime 7/7] RUN mkdir", f"el {M('mkdir')} + {M('chown')} de {M('/app/data')}"),
        ("[runtime 6/7] COPY src/", M("COPY src/")),
        ("exporting to image", "exportar la imagen"),
    ]
    for pref, legible in tabla_n:
        if n.startswith(pref):
            return legible
    return M(_esc(n))


# M7: dispersion del build en frio de v2, explicada solo si los logs lo dicen
FRIO_V2 = []
for r in (1, 2, 3):
    log = (EVD / f"build_v2_frio_r{r}.log").read_text(encoding="utf-8", errors="replace")
    t4 = re.search(r"^#\d+ ([\d.]+) Get:4 .*Packages \[([\d.]+ [kM]B)\]", log, re.M)
    t5 = re.search(r"^#\d+ ([\d.]+) Get:5 ", log, re.M)
    pared = float(e2.buscar(rf"-t proyecto:v2 -f Dockerfile \.\s+# frio, repeticion {r}\nreal ([\d.]+)s"))
    FRIO_V2.append((pared, float(t5.group(1)) - float(t4.group(1)) if t4 and t5 else None,
                    t4.group(2) if t4 else None))
_pareds = [p for p, _, _ in FRIO_V2]
_descargas = [d for _, d, _ in FRIO_V2]
M7_OK = all(d is not None for d in _descargas) and \
    (max(_descargas) - min(_descargas)) >= 0.8 * (max(_pareds) - min(_pareds))
if not M7_OK:
    AVISOS.append(f"M7: la dispersion del build en frio de v2 no se explica por la descarga apt: {FRIO_V2}")

# --- parte 3
FIN = e3.s("3.5 Al terminar")
TOTAL = int(e3.buscar(r"^\$ wc -l data/raw/\*\.jsonl\n(?:.+\n)*?\s+(\d+) total"))
verificar(TOTAL >= 10_000_000, "menos de 10 M eventos")
SIM_OK = re.search(r"OK: (\d+) eventos, ([\d.]+) GB, ([\d.]+) s \((\d+) ev/s, ([\d.]+) MB/s\)", FIN)
CICLO_COD, CICLO_S = re.search(r"codigo de salida (\d+), ([\d.]+) s", e3.texto).groups()
verificar(CICLO_COD == "0", "el simulador no salio con 0")
EXIT_ING = e3.buscar(r"^ingestor-tcp ExitCode=(\d+)")
verificar(EXIT_ING == "143", "el ingestor no salio con 143 en compose stop")
IPS = dict((n, ip) for n, ip in re.findall(r"^(\S+) -> ([\d.]+)/\d+$", e3.texto, re.M))
DNS = e3.buscar(r"gethostbyname\('ingestor-tcp'\)\)\"\n([\d.]+)")
verificar(DNS == IPS["ingestor-tcp"], "la resolucion DNS no calza con la IP del ingestor")
VAL = e3.s("Validacion completa")
SENSORES = re.search(r"Sensores distintos\s*:\s*(\d+)", VAL).group(1)
POR_METRICA = eval(re.search(r"Por metrica\s*:\s*(\{.+?\})", VAL, re.S).group(1).replace("\n", ""))  # dict literal del validador
TICKS = int(e3.buscar(r"(\d+) puntos x (\d+) ticks", 2))
PUNTOS = int(e3.buscar(r"(\d+) puntos x (\d+) ticks", 1))
PUNTOS_M = {m: c // TICKS for m, c in POR_METRICA.items()}
verificar(all(c % TICKS == 0 for c in POR_METRICA.values()) and sum(PUNTOS_M.values()) == PUNTOS,
          "los puntos por metrica no suman los puntos del plan")

# --- rendimiento: contenedor (3 corridas) frente a nativo (3 corridas)
EV_S_C = [int(x) for x in re.findall(r"OK: \d+ eventos.*?\((\d+) ev/s", er.texto)]
EV_S_N = [int(x) for x in re.findall(r"OK: \d+ eventos.*?\((\d+) ev/s", eb.texto)]
verificar(len(EV_S_C) == 3 and len(EV_S_N) == 3, "faltan corridas de rendimiento")
MED_C, MED_N = statistics.median(EV_S_C), statistics.median(EV_S_N)
verificar(f"mediana: {int(MED_C)} ev/s" in er.texto and f"mediana: {int(MED_N)} ev/s" in eb.texto,
          "las medianas no coinciden con las registradas por los scripts")
PY_C = er.buscar(r"^(Python 3\.\S+)$")
PY_N = eb.buscar(r"^(Python 3\.\S+)$")
FS_N = eb.buscar(r"^\$ df -hT .*\n\S+\s+(\S+)")
UNAME_N = eb.buscar(r"^\$ uname -srm.*\n(Linux .+)$")
PARAM_C = dict(re.findall(r"^(TOTAL_EVENTOS|N_PROCESOS|BATCH_SIZE)=(\d+)", er.texto, re.M))
PARAM_N = re.search(r"--arch tcp --workers (\d+) --total-events (\d+) --batch-size (\d+)", eb.texto).groups()
verificar((PARAM_C["N_PROCESOS"], PARAM_C["TOTAL_EVENTOS"], PARAM_C["BATCH_SIZE"]) == PARAM_N,
          f"los parametros del contenedor y del nativo no son iguales: {PARAM_C} {PARAM_N}")
verificar(all(n == "10000014" for n in re.findall(r"OK: (\d+) eventos", er.texto + eb.texto)),
          "alguna corrida de rendimiento no genero 10.000.014 eventos")
DELTA = (MED_C - MED_N) / MED_N * 100

# --- permisos
PERM_ERR = ep.buscar(r"ERROR\s+receptor: (sin permiso de escritura en \S+ \(uid \d+\))")
PERM_A = ep.s("A) SIN chown")
PERM_DIR = re.search(r"^\$ \$AUX ls -lnd /w/raw\n(d\S+)\s+\d+\s+(\d+)\s+(\d+)\s", PERM_A, re.M).groups()
verificar(PERM_DIR == ("drwxr-xr-x", "0", "0"), f"la carpeta sin chown no es root 755: {PERM_DIR}")
PERM_FS = ep.buscar(r"^\S+\s+(\S+)\s+\d+\s+\d+\s+\d+\s+\d+%\s+/w$")
PERM_OK = int(ep.buscar(r"^\$ \$AUX sh -c 'ls -ln /w/raw && cat.*\n(?:.+\n)*?(\d+)$"))
PERM_UID = ep.todos(r"^-\S+\s+\d+\s+(\d+)\s+(\d+)\s+\d+.*part-\d+\.jsonl$")
verificar(PERM_UID and all(u == ("10001", "10001") for u in PERM_UID), "los archivos no son del UID 10001")
PERM_DEF = "\n".join(l for l in ep.texto.splitlines() if re.match(r"^(BASE|EVENTOS|AUX)=", l))

# --- limite del ingestor (valores crudos + muestreo durante la corrida)
with open(EVD / "limite_ingestor_crudo.tsv", encoding="utf-8") as f:
    CRUDO = list(csv.DictReader(f, delimiter="\t"))
EXCEDE = [r for r in CRUDO if r["memory.peak_B"].isdigit() and int(r["memory.peak_B"]) > int(r["memory.max_B"])]


def muestreo(lim):
    """Resumen del muestreo cada 20 ms del cgroup del ingestor para un limite."""
    ruta = EVD / f"limite_ingestor_muestreo_{lim}.tsv"
    with open(ruta, encoding="utf-8") as f:
        filas = [r for r in csv.DictReader(f, delimiter="\t") if r["memory.current_B"].isdigit()]
    sobre = [r for r in filas if r["memory.max_B"].isdigit() and int(r["memory.current_B"]) > int(r["memory.max_B"])]
    return {
        "archivo": ruta.relative_to(REPO).as_posix(), "n": len(filas), "sobre": len(sobre),
        "sock_sobre": max((int(r["sock_B"]) for r in sobre), default=0),
        "max_cur": max(int(r["memory.current_B"]) for r in filas),
        "max_sock": max(int(r["sock_B"]) for r in filas),
        "ev_max": filas[-1]["events_max"],
    }


for r in EXCEDE:
    AVISOS.append(f"I1: con MEM_INGESTOR={r['MEM_INGESTOR']}, memory.peak supera a memory.max en "
                  f"{int(r['memory.peak_B']) - int(r['memory.max_B'])} B")
RSS_OK = [int(r["VmHWM_kB"]) / 1024 for r in CRUDO if r["simulador"] == "0"]
FALLA = [r for r in CRUDO if r["simulador"] != "0"]
OK_MIN = min((r for r in CRUDO if r["simulador"] == "0"), key=lambda r: int(r["memory.max_B"]))
PICO_MAX = max(CRUDO, key=lambda r: int(r["memory.peak_B"]))
LIM_REC = 256 * 1048576
verificar(any(r["MEM_INGESTOR"] == "256m" and r["simulador"] == "0" for r in CRUDO), "no hay corrida OK con 256m")
FACTOR = LIM_REC / int(PICO_MAX["memory.peak_B"])


def mib(b):
    return int(b) / 1048576


# =========================================================================
#  Documento
# =========================================================================
story = []
A = story.append
E = story.extend

# ---------------------------------------------------------------- portada
A(Spacer(1, 40 * mm))
A(P("Laboratorio de Docker", "title"))
A(Spacer(1, 4 * mm))
A(P("Dockerización y orquestación del simulador multiproceso<br/>y el receptor TCP asíncrono", "subtitle"))
A(Spacer(1, 14 * mm))
E(tabla([
    ["Campo", "Detalle"],
    ["Asignatura", "Programación Avanzada"],
    ["Guía", "Laboratorio Docker (Lab F2-3): Partes 1, 2 y 3"],
    ["Integrantes", "<b>[COMPLETAR NOMBRES]</b>"],
    ["Fecha", "28 de septiembre de 2026"],
    ["Repositorio", "LabPrograAvanzada (se adjunta como .zip con los archivos fuente)"],
], anchos=[1, 3]))
A(Spacer(1, 6 * mm))
A(P("Entorno de medición", "h2"))
E(tabla([
    ["Elemento", "Valor"],
    ["Host", "Windows 11 Pro (10.0.26200) con Docker Desktop sobre WSL2"],
    ["Docker", f"{PLATAFORMA}; Engine {ENGINE}; Compose {COMPOSE}; BuildKit"],
    ["VM Linux de Docker", f"kernel {KERNEL}, {NCPU} CPU, {fmt(int(RAM_B) / 2**30)} GiB de RAM, cgroup v{CGV}"],
    ["Imágenes base", "python:3.12 y python:3.12-slim (Debian 13 «trixie»), descargadas antes de medir"],
], anchos=[1, 3]))
A(P(f"Las salidas de terminal de este informe las obtuvimos en este equipo con Docker Engine {ENGINE}, usando los "
    f"scripts de la carpeta {M('lab/')}. La excepción son las capturas 1 y 3, que son pantallazos de la sesión manual "
    f"que hizo el grupo. Cada script guarda su salida completa en {M('lab/evidencias/')} y bajo cada captura indicamos "
    "el archivo y las líneas de donde sale. Como trabajamos con Docker Desktop en Windows, los comandos que miran el "
    f"host desde fuera del contenedor ({M('/proc')}, {M('lsns')}, {M('dmesg')}, {M('ip')}, {M('ping')}) los corrimos "
    f"dentro de la VM Linux de Docker, como indica la guía, a través de un contenedor con {M('--pid=host')} o "
    f"{M('--net=host')}.", "small"))
A(PageBreak())

# ---------------------------------------------------------------- 0
A(P("0. Lo que contenerizamos", "h1"))
E(codigo(
""" simulador-puerto (N procesos)                          ingestor-tcp (asyncio)
 +--------------------------+   red privada red-datos-lab  +-------------------------+
 | worker 0 -- socket TCP --+----------------------------->| part-000.jsonl          |
 | worker 1 -- socket TCP --+----------------------------->| part-001.jsonl          |  bind mount
 | ...                      |    ingestor-tcp:9009 (DNS)   | ...                     +--> ./data/raw
 | worker N -- socket TCP --+----------------------------->| manifiesto_receptor.json|   (host)
 +--------------------------+ <---- acuse tras fsync ------+-------------------------+"""))
A(P(f"El proyecto tiene dos programas. El simulador ({M('python -m src.main --arch tcp')}) es el generador "
    "multiproceso de la Fase 1: cada worker genera sus eventos y los envía por su propia conexión TCP, así que los "
    f"procesos no comparten nada entre ellos. El receptor ({M('src/receptor_tcp.py')}) es un servidor {M('asyncio')} "
    f"que escribe un {M('part-NNN.jsonl')} por worker, siempre con líneas completas. Cuando un worker termina de "
    f"enviar, el receptor hace {M('flush')} y {M('fsync')} y recién ahí le responde cuántas líneas quedaron escritas. "
    "El simulador solo sale con código 0 si todos esos conteos coinciden con lo que envió."))

# ---------------------------------------------------------------- 1
A(PageBreak())
A(P("1. Parte 1: aislamiento por namespaces y red (entregable 1)", "h1"))
A(P("1.1 Contenedor Python en modo interactivo", "h2"))
E(imagen(REPO / "lab/evidencias/capturas_grupo/1.1_sesion_interactiva.png",
         f"Captura 1: sesión interactiva con {M('docker run -it --rm --name lab-cli python:3.12-slim bash')}. "
         "Adentro el sistema es Debian 13 y el hostname es el ID corto del contenedor.",
         "Fuente: lab/evidencias/capturas_grupo/1.1_sesion_interactiva.png (pantallazo del grupo)",
         ancho_max=ANCHO * 0.8))
E(terminal(e1.s("1.1 Contenedor"), "Captura 2: los mismos comandos, sin modo interactivo, en el equipo de medición.", e1))

A(P("1.2 Namespaces: el mismo proceso, dos PID distintos", "h2"))
E(imagen(REPO / "lab/evidencias/capturas_grupo/1.2a_vista_dentro.png",
         "Captura 3: vista desde dentro en la sesión manual del grupo. El proceso Python es el PID 1.",
         "Fuente: lab/evidencias/capturas_grupo/1.2a_vista_dentro.png (pantallazo del grupo)",
         ancho_max=ANCHO * 0.9))
A(P(f"La captura 3 es de otra instancia de {M('lab-ns')}, creada a mano por el grupo, y por eso sus PIDs visibles "
    "(1, 7, 15, 16) no son los de la captura 4. Las capturas 4 y 5 sí son de la misma instancia, creada por "
    f"{M('lab/parte1_windows.sh')}, y a ella corresponden el PID {PID} y el namespace {M(NS_C)}.", "small"))
E(terminal(e1.s("1.2 a)"), "Captura 4: vista desde dentro del contenedor lab-ns.", e1))
HOST_DEF = e1.buscar(r"^(HOST=.+)$")
E(terminal(HOST_DEF + "\n\n" + e1.s("1.2 b)"),
           f"Captura 5: vista desde el host (la VM Linux de Docker Desktop). {M('$HOST')} está definido en la primera "
           "línea: es un shell en la VM.", e1))
E(tabla([
    ["Observación", "Dentro del contenedor", "Desde el host"],
    [f"PID del proceso {M('python -c &quot;...sleep(3600)&quot;')}", "1",
     f"{PID} ({M('docker top')} y {M('docker inspect')})"],
    [f"{M('NSpid')} en {M(f'/proc/{PID}/status')}", "—", f"{M(NSPID)}: la misma tarea con sus dos PID"],
    ["PIDs visibles", PIDS_VIS, "todos los de la VM"],
    ["Namespace PID", M(NS_C), M(NS_H)],
    [M(f"lsns -p {PID}"), "propios: " + ", ".join(NS_PROPIOS), "compartidos con el host: " + ", ".join(NS_HOST)],
], anchos=[1.3, 1.3, 1.6]))
if len(NS_HOST) == 1:
    _nsh = f"el namespace {M(NS_HOST[0])} es el del host: Docker no aísla ese namespace por defecto"
else:
    _nsh = (f"los namespaces {lista_es([M(t) for t in NS_HOST])} son los del host: Docker no aísla esos "
            "namespaces por defecto")
A(P(f"Lo que se ve es un solo proceso del kernel con dos identidades: dentro del contenedor es el PID 1 y en el host es "
    f"el PID {PID}. El kernel lo muestra en la línea {M('NSpid: ' + NSPID)} de {M(f'/proc/{PID}/status')}. Los "
    f"identificadores del namespace PID son distintos ({NS_C} dentro y {NS_H} en el host), lo que confirma que el "
    f"aislamiento funciona. {M('lsns')} muestra además que {_nsh}, y por eso en la Parte 2 la imagen deja de correr "
    "como root."))

A(P("1.3 IP virtual y red del contenedor", "h2"))
E(definicion("lab/parte1_windows.sh", "IP"))
E(terminal(sin(e1.s("1.3 IP virtual"), r"^\(JSON guardado"),
           "Captura 6: JSON de NetworkSettings (también va como "
           f"{M('lab/evidencias/parte1_networksettings.json')}), IP del contenedor, subred de la red bridge, la "
           f"interfaz {M('docker0')} y el ping desde la red de la VM.", e1))
A(P(f"El contenedor tiene la IP virtual {IP}/{PREF} en la red {M('bridge')} por defecto (subred {SUBNET}), y su puerta "
    f"de enlace es {GW}, que es la dirección de {M('docker0')} en la VM ({DOCKER0}). Primero el grupo probó el "
    f"{M('ping')} desde PowerShell y desde la distro {M('docker-desktop')}, y se perdieron todos los paquetes, porque "
    "en Docker Desktop la red bridge solo existe dentro de la VM. Desde el namespace de red de la VM, que es donde está "
    f"{M('docker0')}, el ping sí responde ({PING.replace('packets transmitted', 'enviados').replace('packets received', 'recibidos').replace('packet loss', 'de pérdida')}). "
    "Como esta IP cambia con cada contenedor, en la Parte 3 los servicios se buscan por nombre."))

# ---------------------------------------------------------------- 2
A(PageBreak())
A(P("2. Parte 1: cgroups y OOM Killer (entregable 2)", "h1"))
E(definicion("lab/parte1_windows.sh", "BOMB"))
E(terminal(OOM_SEC, "Captura 7: memory_bomb.py con techo de 100 MB y sin swap. Código 137, OOMKilled=true y las líneas "
                    f"del kernel de ese contenedor (el dmesg se filtra por su ID y por el PID {OOM_PID}).", e1))
E(terminal(e1.s("1.4 El limite"),
           f"Captura 8: el límite lo pone el cgroup ({M('memory.max')} = {MEMMAX} B = 100 MiB). El {M('docker stats')} "
           f"se hizo sobre {M('lab-limite')} porque {M('lab-oom')} ya había sido terminado por el OOM killer y "
           f"{M('docker stats')} no muestra contenedores detenidos.", e1))
E(terminal(sin(e1.s("1.4 Repeticion"), r"^$"), "Captura 9: la misma prueba con 512 MB.", e1))
E(tabla([
    ["Prueba", "Resultado"],
    [M("-m 100m --memory-swap 100m"), f"último mensaje «Reservados: {ULT100} MB»; duró {seg(T100)} s"],
    [M("echo $?"), f"{ECHO} (128 + 9, SIGKILL)"],
    [M("docker inspect"), M(OOMK.strip())],
    [M("dmesg"), ("constraint=CONSTRAINT_MEMCG; " if DM_CONS else "") +
     M(f"Killed process {DM_PID} (python) … anon-rss:{DM_RSS}kB … UID:{DM_UID}")],
    [M("-m 512m"), f"llegó a «Reservados: {ULT512} MB» y duró {seg(T512)} s, también con 137"],
], anchos=[1.2, 3]))
A(P("Análisis", "h2"))
RATIO = float(T512) / float(T100)
ANALISIS = (
    "El código 137 es 128 + 9, o sea que el proceso terminó por SIGKILL. No hubo un error en Python: el cgroup del "
    f"contenedor llegó a su límite de 100 MiB (el kernel lo marca como {M('CONSTRAINT_MEMCG')} aunque la VM tenía "
    "memoria libre) y el OOM killer mató al proceso. SIGKILL no se puede capturar ni ignorar, así que Python no alcanzó "
    f"a ejecutar nada más: no hay {M('MemoryError')}, ni traceback, ni bloque {M('finally')}, y los buffers no se "
    "vacían. Por eso el log se corta en la última línea «Reservados». Si esto pasara durante la ingesta se perdería lo "
    f"que estuviera en memoria. Con 512 MB el mismo programa duró {fmt(RATIO)} veces más: el límite depende de la "
    "configuración del contenedor, no del programa.")
N_ANA = lineas_renderizadas(ANALISIS)
verificar(N_ANA <= 8, f"el analisis del OOM ocupa {N_ANA} lineas (maximo 8)")
A(P(ANALISIS))

# ---------------------------------------------------------------- 3
A(PageBreak())
A(P("3. Parte 2: Dockerfile multi-etapa y .dockerignore (entregable 3)", "h1"))
A(P("Las decisiones más importantes del Dockerfile (v2) y por qué las tomamos:"))
E(tabla([
    ["Decisión", "Motivo"],
    [f"Dos etapas: {M('builder')} (venv con las dependencias) y {M('runtime')}",
     "Lo que se instala solo para construir no llega a la imagen final."],
    [f"{M('requirements.txt')} se copia antes que {M('src/')}",
     f"La capa del {M('pip install')} queda en caché y cambiar código no reinstala las dependencias."],
    [f"{M('tini')} como {M('ENTRYPOINT')} y {M('CMD')} en forma exec",
     "El PID 1 recibe SIGTERM y se lo pasa a Python; además recoge los procesos zombie de los workers."],
    [f"Usuario {M('appuser')} con UID/GID fijos 10001",
     "El proceso no corre como root, y con un UID fijo se le pueden dar permisos a la carpeta montada (sección 7)."],
    [f"El código queda como dueño {M('root')}; solo {M('/app/data')} es de appuser",
     "El proceso puede leer su código pero no modificarlo."],
    [f"{M('PYTHONUNBUFFERED')}, {M('PYTHONDONTWRITEBYTECODE')}, {M('PYTHONFAULTHANDLER')}",
     f"Los logs salen al momento, no se escriben {M('.pyc')} (se puede usar raíz de solo lectura) y hay traza si "
     "falla código nativo."],
    [f"venv con {M('--without-pip')} y sin {M('build-essential')}",
     f"{M('requirements.txt')} está vacío (solo biblioteca estándar), así que el compilador solo alargaría el build. "
     "En el Dockerfile quedó comentado dónde se agregaría si hiciera falta."],
], anchos=[1.5, 2.5]))
A(P("Efecto del .dockerignore", "h2"))
E(terminal(e2.s("2.1 .dockerignore"), "Captura 10: contexto que se envía al daemon con Dockerfile.v0, sin y con "
                                      ".dockerignore, con el dataset de la Parte 3 ya generado en data/raw.", e2))
E(tabla([
    [f"Build de Dockerfile.v0 ({M('COPY . .')})", "Contexto transferido", "Imagen resultante"],
    ["Sin .dockerignore", f"{tam(CTX[0][0])} en {seg(CTX[0][1])} s",
     f"{tam(IMG_CTX[0])} (el dataset queda dentro de la imagen)"],
    ["Con .dockerignore", f"{tam(CTX[1][0])} en {seg(CTX[1][1])} s", tam(IMG_CTX[1])],
], anchos=[1.5, 1.2, 1.8]))
A(P("Dockerfile (v2) comentado", "h2"))
E(codigo((REPO / "Dockerfile").read_text(encoding="utf-8"), "Fuente: Dockerfile"))
A(P(".dockerignore", "h2"))
E(codigo((REPO / ".dockerignore").read_text(encoding="utf-8"), "Fuente: .dockerignore"))

# ---------------------------------------------------------------- 4
A(PageBreak())
A(P("4. Parte 2: tabla comparativa con mediciones propias (entregable 4)", "h1"))
N_REPS = len(PIP_REPS)
E(tabla([
    ["Versión", "Estrategia", "Tamaño final", f"Build en frío (s, mediana de {N_REPS})",
     f"Rebuild tras 1 línea (s, mediana de {N_REPS})", f"Capa {M('pip install')} en el rebuild"],
    *[[f[0], tildes(f[1]).replace("COPY . .", M("COPY . .")), signo(tam(f[2])), signo(seg(f[3].replace(" s", ""))),
       signo(seg(f[4].replace(" s", ""))), dec(f[5])] for f in T2],
], anchos=[0.7, 1.9, 0.8, 0.9, 0.9, 1.0], negrita_ultima=True))
A(P(f"Todas las repeticiones, en segundos: {dec(REPS_TXT.replace('Repeticiones (s): ', '')).replace('frio', 'en frío')} "
    f"(fuente: {M('lab/evidencias/parte2_tabla.md')}).", "small"))
E(terminal(cmds(e2.s("2.2 / 2.4"), "time docker build", "docker images", "docker history"),
           "Captura 11: builds en frío (3 repeticiones), tamaños e historia de capas de v2.", e2))
E(terminal(e2.s("2.4 Prueba de la cache"),
           f"Captura 12: rebuild tras cambiar una línea de src/receptor_tcp.py (3 repeticiones), estado de la capa "
           f"{M('pip install')} en cada una y tiempo de cada paso del rebuild de v2 y de v0 según los logs "
           f"{M('--progress=plain')}.", e2))
A(P("Lectura de la tabla", "h2"))
DETALLE = [(t, nombre_paso(n)) for t, n in sorted(PASOS_T, reverse=True) if t > 0]
SUMA = sum(t for t, _ in PASOS_T)
A(P(f"La caché se nota más en la capa de dependencias que en el tiempo total. En los {N_REPS} rebuilds, la capa "
    f"{M('pip install')} se volvió a ejecutar en v0 ({serie([v0.rstrip('s') for _, v0, _, _ in PIP_REPS])}) y quedó "
    f"como CACHED en v1 y v2. Como {M('requirements.txt')} está vacío, esa capa demora poco, y por eso la diferencia "
    f"total entre v0 y v2 es chica ({signo(V['Δ v0→v2'][4])}). Con dependencias reales, v0 las reinstalaría cada vez que se "
    "cambia una línea de código."))
A(P(f"Según el log del rebuild de v2 (repetición 1), {PASOS_CACHED} pasos salieron de la caché y los que tomaron "
    f"tiempo fueron {lista_es([f'{n} ({seg(t)} s)' for t, n in DETALLE])}. Suman {seg(round(SUMA, 1))} s de los "
    f"{seg(PARED_V2_R1)} s que duró esa repetición; el resto es el arranque del cliente y de BuildKit, que el log no "
    "detalla. La mayor parte del rebuild se va en las dos consultas de metadatos al registro."))
A(P(f"El tamaño depende sobre todo de la imagen base: el cambio de {M('python:3.12')} a {M('python:3.12-slim')} es lo "
    f"que baja la imagen de {tam(V['v0'][2])} a {tam(V['v2'][2])}. Como no hay dependencias compiladas, v1 y v2 pesan "
    f"casi lo mismo. La ventaja del multi-etapa aparecería si alguna dependencia necesitara {M('gcc')}, porque el "
    "compilador se quedaría en la etapa builder."))
if M7_OK:
    A(P("Los builds en frío de v2 variaron bastante (" + lista_es([f"{seg(p)} s" for p in _pareds]) + "). En los "
        f"logs la diferencia está en el {M('apt-get update')}: descargar el índice de paquetes de Debian "
        f"({FRIO_V2[0][2]}) tomó " + lista_es([f"{seg(round(d, 1))} s" for d in _descargas]) + " en cada repetición, "
        "así que depende de la red y no del Dockerfile. v0 y v1 no instalan paquetes, por eso no tienen esa variación."))

# ---------------------------------------------------------------- 5
A(PageBreak())
A(P("5. Parte 2: evidencia del hardening (entregable 5)", "h1"))
E(terminal(e2.s("2.4 Hardening"), "Captura 13: v2 corre con el UID 10001 y el venv; v0 corre como root. appuser no "
                                  "puede modificar su propio código.", e2))
E(terminal(cmds(e2.s("2.4 SIGTERM en el PID 1: docker stop sin init"), "docker exec"),
           "Captura 14: el PID 1 de cada imagen.", e2))
E(terminal(e2.s("2.4 SIGTERM en el PID 1 con el plazo estandar"),
           f"Captura 15: {M('docker stop')} con el plazo de 10 s que usa la guía ({M('--stop-timeout 10')}), con los "
           f"logs de ambos contenedores.", e2))
filas_stop = [["Contenedor", f"PID 1 ({M('/proc/1/cmdline')})", "Plazo", M("time docker stop") + " (s)", "ExitCode",
               "Captura"]]
if PLAZO_ESTABLE:
    # sin-init-def: las 3 repeticiones de la captura 17 (docker events)
    _t_def = sorted(set(t for t, _ in T_DEFS))
    _e_def = sorted(set(c for _, c in T_DEFS))
    filas_stop += [
        ["sin-init-def (v0)", M(PID1_SIN), _esc("sin fijar (<nil>)"), " / ".join(seg(t) for t in _t_def),
         " / ".join(_e_def), "17"],
        ["con-init (v2)", M(PID1_CON), _esc("sin fijar (<nil>)"), seg(STOPS["con-init"][2]), STOPS["con-init"][3], "18"],
    ]
filas_stop += [
    ["sin-init-10 (v0)", M(PID1_SIN), "10 s", seg(S10[2]), S10[3], "15"],
    ["con-init-10 (v2)", M(PID1_CON), "10 s", seg(C10[2]), C10[3], "15"],
]
E(tabla(filas_stop, anchos=[1.0, 2.1, 0.8, 0.75, 0.6, 0.55]))
A(P(f"En v0 el {M('CMD')} está en forma shell, así que el PID 1 es {M('/bin/sh')} (dash) y Python es su hijo. El "
    f"kernel no aplica la acción por defecto de SIGTERM al PID 1 de un namespace, y {M('sh')} tampoco se la pasa a "
    f"Python, así que la señal de {M('docker stop')} no tiene efecto. Docker espera el plazo completo y después manda "
    "SIGKILL: por eso el código es 137 y el receptor termina sin vaciar nada (su log se queda en «escuchando»). En v2 el "
    f"PID 1 es {M('tini')}, que le reenvía SIGTERM a Python. El receptor atiende la señal dentro del bucle "
    f"{M('asyncio')}: deja de aceptar conexiones, cada conexión escribe sus líneas completas, hace {M('flush')} y "
    f"{M('fsync')}, y el proceso sale con 143 (128 + 15), que es el código de un apagado limpio."))
E(codigo(
"""# src/receptor_tcp.py (extracto)
for sig in (signal.SIGTERM, signal.SIGINT):
    loop.add_signal_handler(sig, _al_recibir, sig)   # corre entre dos await, con estado consistente
...
log.info("%s recibido: cerrando sockets y haciendo flush del .jsonl", nombre)
server.close()                  # deja de aceptar conexiones
for t in activas: t.cancel()    # cada conexion escribe sus lineas completas, flush + fsync y cierra
...
return 128 + recibida[0]        # 143: "termine por SIGTERM, despues de vaciar\"""", "Fuente: src/receptor_tcp.py, función servir()"))
if PLAZO_ESTABLE:
    A(P("Sobre el plazo por defecto", "h2"))
    E(terminal(e2.s("2.4 Plazo de docker stop"),
               f"Captura 16: contenedor creado sin {M('--stop-timeout')}. {M(_esc('StopTimeout=<nil>'))}: el "
               "contenedor no fija un plazo propio y se aplica el del daemon.", e2))
    E(terminal(EVT, f"Captura 17: {M('docker events')} durante tres {M('docker stop')} de v0 sin plazo fijado: hora del "
                    "SIGTERM (signal=15) y del SIGKILL (signal=9) que envió el daemon.", e2))
    E(terminal(cmds(e2.s("2.4 SIGTERM en el PID 1: docker stop sin init"), "docker run -d --name con-init",
                    "docker inspect sin-init con-init", "docker stop con-init", "docker inspect con-init",
                    "docker logs con-init"),
               f"Captura 18: {M('docker stop')} de v2 (con-init) sin plazo fijado: sale en {seg(STOPS['con-init'][2])} s "
               f"con {STOPS['con-init'][3]}, porque tini le pasa SIGTERM a Python antes de que venza el plazo del daemon.",
               e2))
    A(P(f"Sin {M('--stop-timeout')} el contenedor queda con {M(_esc('StopTimeout=<nil>'))}, o sea, sin un plazo propio, "
        f"y se usa el del daemon. Con {M('docker events')} medimos ese plazo en tres repeticiones: entre el SIGTERM "
        f"y el SIGKILL pasaron {serie(PLAZOS)}, y {M('docker stop')} tardó {serie([t for t, _ in T_DEFS])}, no los 10 s "
        "de la guía. Para medir con el valor que asume la guía repetimos "
        f"la prueba con {M('--stop-timeout 10')} (captura 15). En Compose esto no influye, porque ahí "
        f"{M('stop_grace_period: 30s')} fija el plazo.", "small"))
else:
    A(P(f"Sin un plazo explícito, el tiempo observado no fue reproducible entre corridas; por eso se fija "
        f"{M('--stop-timeout 10')}, el valor que asume la guía.", "small"))

# ---------------------------------------------------------------- 6
A(PageBreak())
A(P("6. Parte 3: docker-compose.yml parametrizado y .env (entregable 6)", "h1"))
E(tabla([
    ["Lo que pide la guía", "Cómo lo resolvimos"],
    ["Dos servicios que se comunican por nombre",
     f"{M('simulador-puerto')} usa {M('TCP_HOST=ingestor-tcp')}, que el DNS interno resuelve a {DNS}"],
    ["Red privada", f"{M('red-datos-lab')}, con driver bridge, separada de la bridge por defecto"],
    ["Receptor alcanzable", f"{M('BIND_HOST: 0.0.0.0')}; con 127.0.0.1 el otro contenedor no podría conectarse"],
    ["El simulador no parte antes de tiempo", f"{M('depends_on: condition: service_healthy')} y un healthcheck que abre el puerto"],
    ["Persistencia en el host", f"bind mount {M('${HOST_DATA_DIR}:${DATA_DIR}')} hacia {M('./data/raw')}"],
    ["Parametrización", f"todo sale del {M('.env')}, y cada variable tiene un valor por defecto {M('${VAR:-...}')}"],
    ["Límites", f"{M('mem_limit')} por servicio ({M('MEM_INGESTOR=1g')} y {M('MEM_SIMULADOR=512m')}, los valores de "
                f"la guía) y {M('stop_grace_period: 30s')} para el flush final"],
], anchos=[1.4, 2.6]))
A(P(f"Además de lo que pide la guía, no usamos {M('init: true')} porque la imagen ya trae tini como ENTRYPOINT y "
    "quedarían dos init. El puerto se publica solo en 127.0.0.1, para poder depurar desde el host sin exponer el "
    f"ingestor a la red local. Y los dos servicios comparten un bloque {M('x-endurecido')} con raíz de solo lectura "
    f"({M('tmpfs: /tmp')}), {M('cap_drop: [ALL]')} y {M('no-new-privileges')}."))
E(terminal(cmds(e3.s("3.4 Validar"), "docker compose up", "docker compose ps"),
           "Captura 19: el stack levantado, con el ingestor en estado healthy.", e3))
E(terminal(sin(e3.s("3.4 Red privada"), r"^$"),
           "Captura 20: los dos contenedores en la red privada, la resolución por nombre desde el simulador y el "
           "consumo durante la ingesta.", e3))
A(P("docker-compose.yml", "h2"))
E(codigo((REPO / "docker-compose.yml").read_text(encoding="utf-8"), "Fuente: docker-compose.yml"))
A(P(".env (copia de .env.example, con valores de ejemplo y sin secretos; el .env está en .gitignore)", "h2"))
E(codigo((REPO / ".env.example").read_text(encoding="utf-8"), "Fuente: .env.example"))

# ---------------------------------------------------------------- 7
A(PageBreak())
A(P("7. Parte 3: persistencia de los 10 millones de eventos (entregable 7)", "h1"))
vivo = e3.s("3.5 Durante")
vivo_corto = "\n\n--- ".join([b for b in vivo.split("\n\n--- ") if b.strip()][:3])
E(terminal(vivo_corto, "Captura 21: durante la ingesta los .jsonl crecen en el disco del host (equivale a "
                       f"{M('watch -n 2 &apos;ls -lh data/raw/ &amp;&amp; wc -l data/raw/*.jsonl&apos;')}).", e3))
E(terminal(cmds(FIN, "docker compose ps", "wc -l", "du -sh", "head -n 2 data", "docker compose logs --no-log-prefix"),
           f"Captura 22: al terminar, simulador-puerto queda Exited (0), hay {fmt(TOTAL, 0)} líneas en data/raw y se ve "
           f"la estructura del evento ({M('head -n 2')}).", e3))
E(terminal(cmds(FIN, "docker compose logs ingestor-tcp", "head -n 9"),
           "Captura 23: el receptor confirma cada archivo completo (acuse después del fsync) y lo anota en el manifiesto.", e3))
E(terminal(e3.s("3.5 Cierre limpio"),
           "Captura 24: la prueba final. docker compose stop (el ingestor sale con 143 después del flush), docker "
           "compose down, y los datos siguen en el host.", e3))
E(terminal(e3.s("Validacion completa"), "Captura 25: validación de todas las líneas, campo por campo.", e3))
A(P(f"El total es {fmt(TOTAL, 0)} y no 10.000.000 porque, desde la Fase 1, {M('TOTAL_EVENTOS')} funciona como un "
    f"mínimo: los {PUNTOS} puntos de medición reportan por ciclos completos de 15 s, y 10.000.000 / {PUNTOS} "
    f"redondeado hacia arriba da {fmt(TICKS, 0)} ciclos; {fmt(TICKS, 0)} × {PUNTOS} = {fmt(TICKS * PUNTOS, 0)}. Los "
    f"{PUNTOS} puntos son combinaciones de sensor y métrica ("
    + ", ".join(f"{c} de {M(m)}" for m, c in PUNTOS_M.items()) + f") repartidas en {SENSORES} sensores "
    "físicos, que es lo que el validador cuenta como «Sensores distintos»."))
A(P("Además del conteo, cada worker recibió del receptor el acuse con su conteo exacto después del "
    f"{M('fsync')}, el manifiesto registra el total recibido y los archivos completos, y {M('bench.validar --profundo')} "
    f"revisó todas las líneas sin errores. Esa corrida generó los eventos en {seg(SIM_OK.group(3))} s "
    f"({fmt(int(SIM_OK.group(4)), 0)} ev/s según el log del simulador) y el ciclo completo, desde {M('up')} hasta "
    f"{M('Exited (0)')}, tomó {seg(CICLO_S)} s."))
A(P("Permisos de la carpeta montada con un sistema de archivos Linux", "h2"))
A(P(f"En este equipo {M('data/raw')} es una carpeta de Windows. El bind mount de Docker Desktop no aplica UIDs (los "
    f"archivos aparecen como del usuario de Windows), así que el {M('chown 10001:10001')} de {M('lab/parte3.sh')} no "
    f"se pone a prueba. Para probarlo con permisos reales, {M('lab/prueba_permisos.sh')} levanta el mismo stack con la "
    f"carpeta de datos en un sistema de archivos Linux de la VM de Docker ({M(PERM_FS)}):"))
E(terminal(PERM_DEF + "\n\n" + sin(PERM_A, r"^$"),
           f"Captura 26: la carpeta es de root con permisos 755 ({M(' '.join([PERM_DIR[0], PERM_DIR[1], PERM_DIR[2]]))}) "
           "y no se hace chown. El ingestor (UID 10001) no puede escribir, se reinicia y el simulador no llega a partir.", ep))
E(terminal(sin(ep.s("B) CON chown"), r"^$"), "Captura 27: la misma carpeta con chown -R 10001:10001. La ingesta "
                                            "termina y los archivos quedan a nombre del UID 10001.", ep))
A(P(f"Sin {M('chown')}, el receptor registra «{M(_esc(PERM_ERR))}» y no escribe nada. Con "
    f"{M('chown -R 10001:10001')}, el mismo stack escribe {fmt(PERM_OK, 0)} eventos en archivos del UID 10001. O sea que "
    "el usuario sin privilegios y el cap_drop funcionan con permisos reales, siempre que la carpeta montada sea del "
    "UID 10001."))

# ---------------------------------------------------------------- 8
A(PageBreak())
A(P("8. Conclusión (entregable 8)", "h1"))
LIM_OK = OK_MIN["MEM_INGESTOR"]
if DELTA < 0:
    REND = (f"En rendimiento, el stack con contenedores procesó {fmt(MED_C, 0)} ev/s, un {fmt(-DELTA)} % menos que la "
            f"misma ejecución sin Docker en WSL2 ({fmt(MED_N, 0)} ev/s; mediana de 3 corridas por lado, Anexo B). La comparación "
            f"no es exacta: el contenedor escribe en C: a través del bind mount y la corrida nativa en {FS_N}, y la "
            f"versión de Python no es la misma ({PY_C.split()[1]} en la imagen y {PY_N.split()[1]} en WSL2).")
else:
    REND = (f"En rendimiento, el stack con contenedores procesó {fmt(MED_C, 0)} ev/s y la misma ejecución sin Docker "
            f"en WSL2 {fmt(MED_N, 0)} ev/s (mediana de 3 corridas cada uno, {fmt(DELTA)} %, Anexo B), así que "
            f"contenerizar no le quitó velocidad; eso sí, el contenedor escribe en C: y la corrida nativa en {FS_N}, y "
            f"Python cambia de {PY_N.split()[1]} a {PY_C.split()[1]}.")
CONCL = (REND + f" Lo que sí mejoró claramente fue la imagen: bajó de {tam(V['v0'][2])} a {tam(V['v2'][2])} "
         f"({V['Δ v0→v2'][2].replace('-', '−')}), el {M('.dockerignore')} evitó mandar {tam(CTX[0][0])} de contexto y "
         "la caché evita reinstalar dependencias al cambiar código. En seguridad, los procesos corren con el UID 10001, "
         "sin capacidades, con la raíz en solo lectura, sin poder cambiar su propio código y en una red privada; con "
         "permisos reales de Linux solo escriben si la carpeta montada es suya. La prueba del OOM mostró que un SIGKILL "
         "se lleva lo que haya en buffer, y por eso usamos tini como PID 1 y el receptor atiende SIGTERM "
         f"({seg(C10[2])} s y 143 contra {seg(S10[2])} s y 137 sin init). Para el ingestor recomendamos 256 MiB: su "
         f"RSS se mantiene cerca de {fmt(statistics.median(RSS_OK), 0)} MiB con 4 workers y no crece con el total de "
         f"eventos, porque procesa en streaming; con {LIM_OK} todavía funcionó y con "
         f"{FALLA[0]['MEM_INGESTOR'] if FALLA else '—'} el kernel lo mató (Anexo A). 256 MiB deja ≈{fmt(FACTOR)}× de "
         f"margen sobre el mayor pico medido del cgroup ({fmt(mib(PICO_MAX['memory.peak_B']))} MiB). En el .env dejamos "
         "1g porque es el valor de la guía.")
N_LIN = lineas_renderizadas(CONCL)
verificar(N_LIN <= 15, f"la conclusion ocupa {N_LIN} lineas (maximo 15)")
A(P(CONCL))

# ---------------------------------------------------------------- anexos
A(PageBreak())
A(P("Anexo A. Respaldo de la recomendación de memoria del ingestor", "h1"))
A(P(f"Datos de {M('lab/limite_ingestor.sh')}: 2.000.146 eventos por corrida y 4 workers. Los valores se leen dentro "
    f"del contenedor antes de detenerlo, y MiB = bytes / 1.048.576. Fuente: "
    f"{M('lab/evidencias/limite_ingestor_crudo.tsv')} y {M('limite_ingestor.txt')}.", "small"))
filas = [["Límite", f"{M('memory.max')} (B)", f"{M('memory.peak')} (B)", "Pico cgroup", "Pico RSS (VmHWM)",
          "Reinicios", "Salida sim.", "Eventos en disco"]]
for r in CRUDO:
    marca = " (*)" if r in EXCEDE else ""
    filas.append([r["MEM_INGESTOR"], fmt(int(r["memory.max_B"]), 0), fmt(int(r["memory.peak_B"]), 0) + marca,
                  f"{fmt(mib(r['memory.peak_B']))} MiB", f"{fmt(int(r['VmHWM_kB']) / 1024)} MiB", r["reinicios"],
                  r["simulador"], fmt(int(r["lineas"]), 0)])
E(tabla(filas, anchos=[0.6, 1.1, 1.15, 0.8, 0.85, 0.75, 0.7, 0.85]))
for r in EXCEDE:
    mu = muestreo(r["MEM_INGESTOR"])
    exceso = fmt(int(r["memory.peak_B"]) - int(r["memory.max_B"]), 0)
    base = (f"(*) Con {M('MEM_INGESTOR=' + r['MEM_INGESTOR'])}, {M('memory.peak')} "
            f"({fmt(int(r['memory.peak_B']), 0)} B) quedó {exceso} B por encima de {M('memory.max')} "
            f"({fmt(int(r['memory.max_B']), 0)} B). ")
    if mu["sobre"] > 0 and mu["sock_sobre"] > 0:
        A(P(base + f"En el muestreo cada 20 ms durante la corrida ({M(mu['archivo'])}), {mu['sobre']} muestras "
            f"tuvieron {M('memory.current')} sobre el límite y en ellas la memoria de sockets TCP cargada al cgroup "
            f"llegó a {fmt(mu['sock_sobre'], 0)} B: el exceso corresponde a los buffers de los sockets, que el kernel "
            "carga al cgroup aunque se pase del límite.", "small"))
    else:
        A(P(base + f"Fue un exceso transitorio: en el muestreo cada 20 ms durante la corrida ({M(mu['archivo'])}, "
            f"{mu['n']} muestras) no alcanzamos a ver {M('memory.current')} sobre el límite, así que no le atribuimos "
            "una causa.", "small"))
for r in FALLA:
    if int(r["VmHWM_kB"]) * 1024 > int(r["memory.peak_B"]):
        A(P(f"En {M(r['MEM_INGESTOR'])} el receptor se reinició (reinicios = {r['reinicios']}). {M('memory.peak')} es "
            "del cgroup del contenedor reiniciado, que parte de cero, mientras que VmHWM también cuenta páginas de "
            "archivo compartidas (el intérprete y las bibliotecas) que pueden seguir cargadas al cgroup anterior. Por "
            "eso el RSS aparece mayor que el pico del cgroup.", "small"))

A(P("Anexo B. Rendimiento: contenedores frente a ejecución nativa", "h1"))
A(P(f"Ambos lados usan los mismos parámetros: {M('--arch tcp')}, {PARAM_N[0]} workers, "
    f"{fmt(int(PARAM_N[1]), 0)} eventos pedidos (10.000.014 generados) y lotes de {fmt(int(PARAM_N[2]), 0)}, con el "
    f"receptor en la misma máquina. En contenedores corre {PY_C} y los datos van a {M('data/bench_tmp')} en C: por el "
    f"bind mount ({M('lab/rendimiento_contenedor.sh')}); la corrida nativa usa {PY_N} en {_esc(UNAME_N)} y escribe en "
    f"{FS_N} ({M('lab/baseline_nativo.sh')}).", "small"))
E(terminal(cmds(er.s("Parametros"), "grep", "docker run"), "Parámetros del .env y Python de la imagen.", er))
E(terminal(er.s("Resumen"), "Tres corridas completas en contenedores.", er))
E(definicion("lab/baseline_nativo.sh", "PY", "PUERTO"))
E(terminal(cmds(eb.s("Corrida nativa 1"), "$PY -m src.main"), "Comando de cada corrida nativa (corrida 1).", eb))
E(terminal(eb.s("Resumen"), "Tres corridas nativas en WSL2, sin Docker.", eb))

A(P("Anexo C. Cómo reproducir", "h1"))
E(codigo(
"""cp .env.example .env
bash lab/parte1_windows.sh       # entregables 1 y 2 (en Linux nativo: bash lab/parte1.sh)
bash lab/parte3.sh --limpiar     # entregables 6 y 7 (genera los 10 M de eventos)
bash lab/parte2.sh               # entregables 3, 4 y 5 (usa el dataset para medir el .dockerignore)
bash lab/limite_ingestor.sh 1g 256m 64m 48m 32m   # Anexo A
bash lab/rendimiento_contenedor.sh                # Anexo B, lado contenedores
bash lab/baseline_nativo.sh      # Anexo B, lado nativo (en WSL2/Linux, sin Docker)
bash lab/prueba_permisos.sh      # permisos con un sistema de archivos Linux
python docs/informe_pdf/build_informe.py          # regenera este PDF desde lab/evidencias/"""))


# ---------------------------------------------------------------- pie
def pie(canvas, doc):
    canvas.saveState()
    canvas.setFont("Cal", 8.5)
    canvas.setFillColor(GRIS)
    canvas.drawString(18 * mm, 10 * mm, "Laboratorio Docker · Programación Avanzada")
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Página {doc.page}")
    canvas.restoreState()


doc = SimpleDocTemplate(str(SALIDA), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                        topMargin=16 * mm, bottomMargin=18 * mm,
                        title="Laboratorio Docker - Informe", author="Programación Avanzada")
doc.build(story, onFirstPage=pie, onLaterPages=pie)
print("OK", SALIDA)
print(f"control: conclusion {N_LIN} lineas (max 15), analisis OOM {N_ANA} lineas (max 8)")
for a in AVISOS:
    print("AVISO", a)
