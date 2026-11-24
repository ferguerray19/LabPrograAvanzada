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
