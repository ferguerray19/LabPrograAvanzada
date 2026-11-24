# Fases 2 y 3 en el clúster Spark

La Fase 2 produce `salida_fase2/telemetria_limpia.parquet`. El laboratorio 11 consume esa tabla, usa `en_falla` como origen de la etiqueta y guarda `salida_fase3/caracteristicas.parquet` y `salida_fase3/pipeline_preparacion`.

Copiar `.env.example` a `.env` antes de iniciar el clúster. Si 8080 está ocupado, elegir otro `PUERTO_MASTER_UI` en `.env` (en el equipo de integración se usa 18090). Los puertos internos y el hostname `spark-master` permanecen iguales.

Ejecutar los notebooks de uno en uno y cerrar cada sesión antes de abrir la siguiente. Para laboratorio 11:

```powershell
docker compose exec -T jupyter jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=3600 /opt/workspace/fase3_lab11_feature_engineering.ipynb
```

El notebook incluye la comparación de ventanas de 1, 5 y 15 minutos y el ejercicio de línea base del primer día. Las cifras verificadas se guardan en `salida_fase3/resultados_lab11.json` y las posiciones del vector en `mapa_features.csv`. El informe final está en `../docs/Informe_Lab11.pdf`.

Los notebooks de `historico/` son respaldo de la versión anterior de GitHub. La sección siguiente conserva la explicación de la corrida de Fase 2 del 18 de octubre: sus tiempos son evidencia histórica, no una promesa de duración en otros equipos.

# Fase 2: procesamiento distribuido con PySpark

**Laboratorio de Programación Avanzada · Terminal Puerto Coquimbo, Sitio 3**

Este proyecto levanta un clúster de Spark en Docker y procesa con PySpark dos conjuntos de datos de la Fase 1:

- **El crudo del receptor TCP** (`data/raw`): 10.000.014 eventos JSONL, unos 1,8 GB.
- **El dataset del simulador** (`salida_sitio3`): 6.395.325 lecturas de 7 días, con 9 fallas inyectadas cuya verdad de terreno se conoce.

El resultado es una tabla limpia y etiquetada (`salida_fase2/telemetria_limpia.parquet`), que es el insumo de la Fase 3.

Este archivo tiene dos partes: [cómo hacerlo funcionar](#1-cómo-hacerlo-funcionar) y [cómo funciona el código](#2-cómo-funciona-el-código).

---

## 1. Cómo hacerlo funcionar

### 1.1 Requisitos

- **Docker Desktop** encendido (en Windows, con WSL 2). Debe tener al menos 8 GB de RAM asignados; en este PC tiene 15,6 GB.
- Un navegador.
- Nada más: Python, Java, Spark y Jupyter vienen dentro de la imagen de Docker. No hay que instalar nada en Windows.

### 1.2 Pasos (desde una terminal en la carpeta del proyecto)

**Paso 1. Levantar el clúster.** La primera vez se construye la imagen, lo que toma unos minutos:

```powershell
docker compose up -d --build
```

Las veces siguientes basta con `docker compose up -d`.

Comprobar que quedaron 4 contenedores arriba (`spark-master`, 2 workers y `jupyter`):

```powershell
docker compose ps
```

**Paso 2. Prueba de humo.** Hay que correrla **antes** de abrir el notebook, porque la sesión del notebook ocupa los 4 cores del clúster:

```powershell
docker compose exec jupyter python3 verificar_cluster.py
```

Debe terminar con `Clúster OK: las 4 comprobaciones pasaron.` Las comprobaciones son:

1. Se crea la sesión.
2. Hay un executor por cada worker vivo del master.
3. Todos los executors ven `/opt/workspace/data/raw`.
4. Se leen los 10 M de registros.

**Paso 3. Abrir Jupyter** en <http://localhost:8889>, con el token `lab-sitio3`.

> Ojo: es el puerto **8889**, no el 8888. El 8888 suele estar ocupado por el Jupyter de la Fase 1, que no tiene Spark. Si se abre ahí, la primera celda del notebook lo detecta y se detiene.

**Paso 4. Ejecutar el notebook completo.** Abrir `fase2_pyspark.ipynb` y usar **Kernel → Restart Kernel and Run All Cells**. Tarda unos 7 minutos. Si alguna aserción falla, el notebook se detiene en esa celda.

También se puede ejecutar sin navegador. El notebook queda guardado con las salidas nuevas:

```powershell
docker compose exec -T jupyter jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=3600 /opt/workspace/fase2_pyspark.ipynb
```

**Paso 5. Capturas de la UI de Spark.** La UI del driver, en <http://localhost:4040>, solo existe mientras la sesión está abierta. La última celda (`spark.stop()`) la cierra. Si se necesitan capturas de *Jobs* o *Stages*, hay dos opciones:

- Ejecutar con **Run → Run All Above Selected Cell** parado en la última celda, capturar y después correr `spark.stop()`.
- Revisarla después con el History Server:

  ```powershell
  docker compose --profile history up -d
  ```

  y abrir <http://localhost:18080>.

**Paso 6. Apagar el clúster** al terminar:

```powershell
docker compose down
```

### 1.3 Direcciones útiles

| Dirección | Qué es |
|---|---|
| <http://localhost:8889> | JupyterLab (aquí vive el driver de Spark) · token `lab-sitio3` |
| <http://localhost:8080> | UI del master: workers registrados y aplicaciones |
| <http://localhost:4040> | UI del driver: Jobs, Stages, SQL (solo con la sesión abierta) |
| <http://localhost:18080> | History Server (opcional, perfil `history`) |

### 1.4 Tareas opcionales

**Regenerar `salida_sitio3/`.** Solo hace falta si se borró o se cambió el simulador:

```powershell
docker compose exec -w /opt/workspace jupyter python3 generar_salida_sitio3.py
```

Usa la semilla 42, así que vuelve a producir exactamente los mismos datos.

**Agregar workers:**

```powershell
docker compose up -d --scale spark-worker=3
```

**Cambiar el tamaño del clúster.** Se hace solo en `.env`, con `SPARK_WORKERS`, `SPARK_WORKER_CORES`, `SPARK_WORKER_MEMORY` y `SPARK_DRIVER_MEMORY`. El archivo trae perfiles sugeridos según la RAM de Docker. Se usa el de 8 GB (2 workers × 2 cores × 2 GB + driver de 2 GB = 6 GB) a propósito, para que las mediciones sean comparables entre corridas.

### 1.5 Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| `failed to connect to the docker API` | Docker Desktop está apagado. Abrirlo y esperar a que diga *Engine running*. |
| La primera celda dice "ESTE NOTEBOOK NO ESTÁ CORRIENDO EN EL CLÚSTER" | Se abrió en el Jupyter equivocado. Usar <http://localhost:8889>. |
| El job queda en `RUNNING` y no avanza | El driver no es alcanzable desde los executors. El notebook ya fija `spark.driver.host=jupyter` y `bindAddress=0.0.0.0`; no hay que quitarlos. |
| `verificar_cluster.py` dice 0 executors o "solo 1 de 2" | Hay otra sesión de Spark ocupando los cores, normalmente el notebook abierto. Cerrarla con `spark.stop()` o reiniciar el kernel. |
| `port is already allocated` | Otro programa usa ese puerto. Cambiarlo en `.env` (`PUERTO_JUPYTER`, `PUERTO_MASTER_UI`...). |
| `FileNotFoundException` en los executors | Los workers no ven la carpeta. Todos los contenedores deben montar el proyecto en `/opt/workspace`, y así viene en `docker-compose.yml`. |

---

## 2. Cómo funciona el código

### 2.1 Arquitectura

```
PC con Docker Desktop
├── jupyter       = DRIVER  (notebook, 2 GB)  → arma el plan y reparte tareas
├── spark-master            → registra workers y asigna recursos; no procesa datos
├── spark-worker-1          → executor con 2 cores y 2 GB
├── spark-worker-2          → executor con 2 cores y 2 GB
└── volumen compartido /opt/workspace  (esta misma carpeta)
```

- El **driver** ejecuta el programa: arma el plan de cada consulta, lo divide en tareas y las reparte. Los datos pesados los procesan los **executors** de los workers. Al driver solo vuelven resultados chicos (tablas agregadas, gráficos).
- Los contenedores usan **una sola imagen** (`docker/Dockerfile`): Spark 4.0.1 con Python 3.10, más JupyterLab, pandas, pyarrow, matplotlib y scipy. Así el driver y los executors tienen exactamente la misma versión de Python y de PySpark. Si no coinciden, Spark falla.
- La carpeta del proyecto se monta en **la misma ruta** (`/opt/workspace`) en todos los contenedores. Cada executor lee los archivos por su cuenta, así que todos necesitan verlos en la misma ruta.
- `docker/spark-defaults.conf` configura a todos los nodos:
  - AQE activado (fusiona particiones chicas y parte las gigantes).
  - Serializador Kryo.
  - Registro de eventos para el History Server.
  - Compatibilidad de timestamps con Parquet escrito por pandas.

### 2.2 Archivos del proyecto

| Archivo o carpeta | Para qué sirve |
|---|---|
| `fase2_pyspark.ipynb` | **Notebook principal. Es lo que se entrega.** |
| `primer_contacto.ipynb` | Notebook introductorio y corto: sesión, evaluación perezosa y esquema inferido vs declarado. No cubre la rúbrica completa. |
| `verificar_cluster.py` | Prueba de humo del clúster (paso 2). |
| `generar_salida_sitio3.py` | Simulador de la Fase 1 convertido a script. Genera `salida_sitio3/`. |
| `docker-compose.yml`, `docker/`, `.env` | Definición del clúster y de su tamaño. |
| `data/raw/` | Crudo de la Fase 1: 4 archivos JSONL y el manifiesto del receptor. |
| `data/muestra/` | Muestra de 50 mil eventos para pruebas rápidas. |
| `salida_sitio3/` | Dataset del simulador: telemetría particionada por `fecha` y la verdad de terreno con las 9 fallas. |
| `salida_fase2/` | Lo que produce el notebook (ver 2.5). |
| `capturas/` | Capturas de pantalla y el diagrama del clúster. |
| `CAMBIOS_NOTEBOOK_explicados.md` | Notas de estudio: qué se cambió en el notebook y por qué. |
| `REVISION_RUBRICA.md` | Evaluación actualizada del proyecto según la rúbrica. |
| `Rubrica_Fase2_PySpark (2).pdf` | Rúbrica oficial. |

### 2.3 Herramientas del notebook (sección 0.5)

Son funciones pequeñas que se reutilizan en todo el notebook:

| Función | Qué hace |
|---|---|
| `medir(df)` | Ejecuta la consulta completa con el formato `noop`, que no trae filas al driver, y devuelve la mediana de varias repeticiones. Nunca se mide con `collect()`, porque eso mediría también la red. |
| `plan_fisico(df)`, `mostrar_plan(df)` | Devuelven y muestran el plan físico. Ocultan la parte interna de la tabla cacheada para ver solo la consulta actual. |
| `contar_exchanges(df)` | Cuenta los **shuffles** (`Exchange` de reparto) y los **broadcasts** (`BroadcastExchange`) del plan. |
| `ejecutar_en_grupo(grupo, df)` | Ejecuta la consulta con una etiqueta única (`grupo#uuid`), para poder buscar sus jobs en la UI. Repetir una celda no mezcla corridas. |
| `tareas(grupo)` | Consulta la API REST de la UI (:4040) y devuelve la duración y las filas de shuffle de cada tarea de la última ejecución del grupo. Cuenta cada etapa una vez, recorre todos los intentos y usa solo las tareas exitosas. |
| `resumen_etapa_shuffle(grupo)` | De las etapas que leen un shuffle, toma la de mayor volumen y resume sus tareas: cantidad, mediana, máximo y relación máximo/mediana. Esa relación mide el **straggler**, la tarea que se atrasa. |

Todas las mediciones se guardan en el diccionario `M` y, al final, en `salida_fase2/metricas.json`.

### 2.4 El notebook, sección por sección

Las cifras son las de la última corrida completa (18-10, `salida_fase2/metricas.json`). Los tiempos cambian de una ejecución a otra; los conteos de filas no.

| Sección | Qué hace | Resultado clave | Implicancia |
|---|---|---|---|
| **0.1** Guarda de entorno | Verifica que el notebook corre en el contenedor del clúster. Si no, se detiene. | — | — |
| **0.2** Sesión | Crea la `SparkSession` contra `spark://spark-master:7077` y espera a que se registren los executors. | Espera un executor por worker vivo y se detiene si falta alguno: 2 executors, 4 tareas en paralelo | 1 |
| **0.3** Justificación del `.env` | Lee la RAM real de Docker y los workers desde el master, y comprueba que el clúster cabe. | 6 GB pedidos < 15,6 GB disponibles | 1 |
| **0.4** Cómo trabaja el clúster | Diagrama, prueba de humo, UI :8080 y por qué `collect()` de millones de filas es un error. | — | 1 |
| **1.1** Esquema inferido vs declarado | Lee el crudo JSON de las dos formas y compara tiempos y tipos. | 28,67 s vs 10,93 s; con esquema declarado, `timestamp` queda tipado | 3 |
| **1.2** Evaluación perezosa | Las transformaciones no ejecutan nada; la acción (`count`) sí. `explain()` muestra el filtro empujado a la lectura y la poda de columnas. | 0,20 s vs 11,0 s | 2 |
| **1.3** Particiones de lectura | Explica por qué el crudo queda en 15 particiones: bloques de 128 MB por archivo, empaquetados. | 15 particiones ≈ 4 "olas" con 4 cores | 1 |
| **1.4** Capa *bronze* | Convierte el JSON a Parquet una vez y compara tamaño y velocidad. | 1.791 MB → 22 MB | 8 |
| **2** Perfilado del crudo | Revisa nulos, duplicados, dominios, estados y reparto por sensor. | No hay nada que limpiar: WARN y ALARM son lecturas legítimas | 4 |
| **3** Dataset del simulador | Carga la telemetría y la verdad de terreno. | 6.395.325 filas, 9 fallas | — |
| **3.1** *Partition pruning* | Un filtro por `fecha` hace que Spark abra una sola carpeta. | `PartitionFilters` en el plan | 8 |
| **4** Perfilado del simulador | Revisa nulos (los de `alimentador_id` son estructurales), duplicados y rangos. | 2 duplicados exactos; 109.982 "duplicados por clave" que **no** lo son (muestras válidas de la báscula) | 4 |
| **5** Limpieza con criterio | Quita solo los duplicados exactos, tipa `alimentador_id`, **marca** (no borra) las lecturas degradadas y verifica con aserciones dominios, nulos en columnas obligatorias y valores de `calidad_sensor`. Deja la tabla en caché. | 6.395.323 filas; 124.219 marcadas como no confiables | 4 |
| **6.1** Estrechas vs anchas | Cuenta los shuffles de `filter`, `groupBy`, `distinct`, `orderBy` y `join`. | Las operaciones estrechas no generan shuffle | 5 |
| **6.2–6.3** Particiones de shuffle y AQE | Misma agregación con 200, 8 y 16 particiones, y con AQE. | 4,45 s / 1,08 s / 1,17 s / 2,59 s (8 y 16 quedan cerca; cuál gana cambia entre corridas) | 5 |
| **6.4** Sesgo (*skew*) | `faja_1` tiene el 47 % de las filas. Una ventana por `entidad_id` crea un straggler; con la clave `(entidad_id, variable)` se reparte. | Máximo/mediana 14,1x → 8,5x | 6 |
| **6.5** *Salting* y AQE skewJoin | Reparte la clave gigante en un join con sal aleatoria, o deja que AQE la parta sola. | Tarea más cargada: 3,2 M → 0,5 M filas (sal) o 0,4 M (AQE) | 6 |
| **6.6** *Broadcast join* | Copia la tabla chica a cada executor en vez de hacer shuffle de la grande. | 3 shuffles → 1; 9,30 s → 3,15 s | 7 |
| **6.7** `repartition` vs `coalesce` | Compara las dos formas de bajar a 2 particiones. | `coalesce` no hace shuffle | 5 |
| **6.8** Trampa del *fan-out* | El join ingenuo por entidad duplica filas y marca la semana entera. El *range join* (entidad o alimentador, con `t_inicio <= t < t_fin`) etiqueta bien. | Ingenuo: 6,4 M → 9,4 M filas. Range join: conserva 6.395.323 filas y deja 436.218 lecturas en falla | 7 |
| **7** Escritura y verificación | Escribe en Parquet particionado por `fecha` con `coalesce(1)` (un archivo por día), relee y verifica con aserciones el total, las filas por día, las etiquetas, las marcas de calidad y los tipos (incluido `fecha` como `date`). | 7 carpetas con un archivo cada una | 8 |
| **8** Resumen | Tabla con todas las mediciones; las guarda en `metricas.json`. | — | — |

La columna "Implicancia" usa la numeración del índice del notebook:

1. Procesamiento distribuido.
2. Evaluación perezosa.
3. Esquemas.
4. Calidad de datos.
5. Shuffling.
6. Sesgo.
7. Joins.
8. Almacenamiento columnar y particionado.

### 2.5 Lo que produce

`salida_fase2/` contiene:

| Archivo | Contenido |
|---|---|
| `bronze_raw.parquet/` | El crudo de la Fase 1 en Parquet (sección 1.4). |
| `telemetria_limpia.parquet/fecha=.../` | **Insumo de la Fase 3.** Telemetría deduplicada, tipada, con `sensor_confiable` y etiquetada contra la verdad de terreno (`falla_id`, `tipo_falla`, `severidad`, `en_falla`). |
| `metricas.json` | Todas las mediciones de la corrida. |
| `grafico_particiones.png`, `grafico_straggler.png` | Gráficos de las secciones 6.2 y 6.4. |

### 2.6 Decisiones de diseño que conviene saber explicar

- **Se declara el esquema**, para no leer el crudo dos veces y para tener tipos estables (`timestamp` como fecha, no como texto).
- **No se deduplica por clave**, porque la báscula toma varias muestras válidas en el mismo segundo.
- **Las lecturas degradadas se marcan, no se borran**, porque la Fase 3 tiene que aprender a distinguir una falla del instrumento de una falla del proceso.
- **`alimentador_id` nulo significa "no aplica"**, no cero.
- **El range join usa `t < t_fin`**, igual que el simulador: en `t_fin` la falla ya terminó.
- **F005 no aparece etiquetada.** Duró 21 s y los alimentadores se muestrean cada 60 s, así que ninguna lectura cayó dentro de su ventana.
- **Se escribe con `coalesce(1)` y no con `repartition`**, porque así no se mueven las 6,4 M filas por la red. El costo es que una sola tarea escribe, lo que con unos 50 MB no importa.
