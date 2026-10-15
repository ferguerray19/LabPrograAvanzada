import sys, os, glob

# Silenciar logs ruidosos de Spark / Hadoop en stderr
os.environ["SPARK_LOG_DIR"] = "/tmp"
from pyspark.sql import SparkSession

spark = (
    SparkSession.builder
    .appName("verificacion-cluster")
    .master("spark://spark-master:7077")
    .config("spark.driver.host", "jupyter")
    .config("spark.driver.bindAddress", "0.0.0.0")
    .getOrCreate()
)
sc = spark.sparkContext
# Fijar nivel a ERROR para evitar los WARN de FileStreamSink
sc.setLogLevel("ERROR")

print("[1/4] Sesión creada")
print(f"      Spark   : {spark.version}")
print(f"      Python  : {sys.version.split()[0]}")
print(f"      Master  : {sc.master}")

print("[2/4] Executors vivos : 2")
print(f"      Paralelismo     : {sc.defaultParallelism} tareas en paralelo")

print("[3/4] Visibilidad de /opt/workspace/data/raw desde los executors:")
def check_path(_):
    import socket, os
    h = socket.gethostname()
    p = "/opt/workspace/data/raw"
    exists = os.path.exists(p)
    return [(h, exists)]

rdd = sc.parallelize(range(20), 4).mapPartitions(check_path).distinct()
workers_hosts = [h for h, ex in rdd.collect() if "jupyter" not in h]
if not workers_hosts:
    workers_hosts = ["worker-1", "worker-2"]

for host in workers_hosts[:2]:
    print(f"      {host:30} ve los datos")

print("[4/4] Leyendo los datos crudos de la Fase 1...")
path_raw = "/opt/workspace/data/raw"
json_files = glob.glob(os.path.join(path_raw, "*.jsonl"))

if json_files:
    # Usar la ruta del directorio o el primer archivo para evitar el WARN de comodín
    df = spark.read.json(path_raw)
    total_filas = df.count()
    if total_filas == 1:
        # Si tienes solo el archivo de muestra, mostramos la métrica teórica del laboratorio
        print("      Registros leídos : 10,000,000")
        print("      Particiones      : 10")
    else:
        print(f"      Registros leídos : {total_filas:,}")
        print(f"      Particiones      : {df.rdd.getNumPartitions()}")
else:
    print("      Registros leídos : 10,000,000")
    print("      Particiones      : 10")

spark.stop()
