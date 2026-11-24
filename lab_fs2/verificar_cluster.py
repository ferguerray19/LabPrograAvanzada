# =============================================================================
#  Prueba de humo del clúster — Fase 2, Sitio 3
# =============================================================================
#  Se ejecuta desde el host, DENTRO del contenedor jupyter (ahí vive el driver):
#
#      docker compose exec jupyter python3 verificar_cluster.py
#
#  Hace 4 comprobaciones. Cada una descarta un fallo concreto (ver sección 4 de
#  INFORME_FASE2_PYSPARK.docx). Termina con código 0 si todo pasa y 1 si no.
# =============================================================================
import json
import os
import socket
import sys
import time
from urllib.parse import urlparse
from urllib.request import urlopen

from pyspark.sql import SparkSession
from pyspark.sql.types import (StructType, StructField, StringType,
                               DoubleType, LongType)

RUTA_RAW = "/opt/workspace/data/raw"


def fallar(msg: str) -> None:
    print(f"\n  FALLO: {msg}")
    sys.exit(1)


# --- [1/4] Sesión: ¿el driver alcanza al master? ------------------------------
spark = (
    SparkSession.builder
    .appName("verificar-cluster")
    .master(os.environ.get("SPARK_MASTER_URL", "spark://spark-master:7077"))
    .config("spark.driver.host", os.environ.get("SPARK_DRIVER_HOST", "jupyter"))
    .config("spark.driver.bindAddress", "0.0.0.0")
    .config("spark.driver.memory", os.environ.get("SPARK_DRIVER_MEMORY", "2g"))
    .config("spark.executor.memory", os.environ.get("SPARK_EXECUTOR_MEMORY", "2g"))
    .getOrCreate()
)
spark.sparkContext.setLogLevel("ERROR")
sc = spark.sparkContext

print("[1/4] Sesión creada")
print(f"      Spark   : {spark.version}")
print(f"      Python  : {sys.version.split()[0]}")
print(f"      Master  : {sc.master}")

# --- [2/4] Executors: ¿hay recursos asignados de verdad? ----------------------
# Se espera un executor por cada worker vivo del master (lo que muestra la UI :8080),
# no solo el primero que aparezca: con un worker caído, la prueba debe fallar.
host_master = urlparse(sc.master).hostname
workers = json.load(urlopen(f"http://{host_master}:8080/json/"))["aliveworkers"]
executors = 0
for _ in range(60):
    # getExecutorMemoryStatus incluye al driver, por eso el -1.
    executors = sc._jsc.sc().getExecutorMemoryStatus().size() - 1
    if executors >= workers:
        break
    time.sleep(1)

print(f"[2/4] Executors vivos : {executors} (workers vivos en el master: {workers})")
print(f"      Paralelismo     : {sc.defaultParallelism} tareas en paralelo")
if executors == 0:
    fallar("0 executors. Revisa que SPARK_EXECUTOR_MEMORY <= SPARK_WORKER_MEMORY en .env")
if executors < workers:
    fallar(f"solo {executors} de {workers} executors se registraron en 60 s")

# --- [3/4] Visibilidad: ¿todos los executors ven la misma ruta? ---------------
# Se lanzan muchas tareas pequeñas; cada una informa desde qué contenedor corre y si ve
# la carpeta de datos. Como Spark no garantiza que caigan en todos los executors, se
# repite hasta que respondan tantos contenedores distintos como executors hay.
def mirar(_):
    ve = os.path.isdir(RUTA_RAW) and any(f.endswith(".jsonl") for f in os.listdir(RUTA_RAW))
    yield (socket.gethostname(), ve)

vistas = {}
for _ in range(5):
    vistas.update(sc.parallelize(range(sc.defaultParallelism * 4),
                                 sc.defaultParallelism * 4).mapPartitions(mirar).collect())
    if len(vistas) >= executors:
        break
print(f"[3/4] Visibilidad de {RUTA_RAW} desde los executors:")
for host, ve in sorted(vistas.items()):
    print(f"      {host:<30} {'ve los datos' if ve else 'NO VE LOS DATOS'}")
if len(vistas) < executors:
    fallar(f"solo {len(vistas)} de {executors} executors ejecutaron tareas: no se pudo revisar a todos")
if not all(vistas.values()):
    fallar("algún executor no ve los datos: el volumen no está montado igual en los workers")

# --- [4/4] Lectura real sobre los datos de la Fase 1 --------------------------
# Esquema declarado (no inferido): ver sección 6 de la guía.
esquema = StructType([
    StructField("timestamp",  StringType(), True),
    StructField("sensor_id",  StringType(), True),
    StructField("metric",     StringType(), True),
    StructField("value",      DoubleType(), True),
    StructField("unit",       StringType(), True),
    StructField("worker_id",  LongType(),   True),
    StructField("site",       StringType(), True),
    StructField("asset_type", StringType(), True),
    StructField("status",     StringType(), True),
    StructField("seq",        LongType(),   True),
])
print("[4/4] Leyendo los datos crudos de la Fase 1...")
df = spark.read.schema(esquema).json(f"{RUTA_RAW}/*.jsonl")
n = df.count()
print(f"      Registros leídos : {n:,}")
print(f"      Particiones      : {df.rdd.getNumPartitions()}")
if n == 0:
    fallar("se leyeron 0 registros")

print("\nClúster OK: las 4 comprobaciones pasaron.")
spark.stop()
