#!/usr/bin/env bash
# ============================================================================
#  Parte 3 - Orquestacion con Docker Compose y persistencia de 10 M de eventos
#
#    bash lab/parte3.sh              # falla si data/raw ya tiene .jsonl
#    bash lab/parte3.sh --limpiar    # borra el dataset anterior y regenera
#
#  Levanta ingestor-tcp y simulador-puerto, muestra la red privada y la
#  resolucion por nombre, sigue el crecimiento de los .jsonl en vivo, cuenta
#  los eventos al terminar y hace la prueba definitiva: `docker compose down`
#  y los datos siguen en el host. Todo queda en lab/evidencias/parte3.txt
#  (entregables 6 y 7).
#
#  Opcional: SIN_BUILD=1 usa las imagenes ya construidas.
# ============================================================================
source "$(dirname "$0")/_comun.sh"
registrar parte3.txt

LIMPIAR=no
[ "${1:-}" = "--limpiar" ] && LIMPIAR=si

# ---------------------------------------------------------------------------
titulo "3.1 Parametrizacion con .env"
if [ ! -f .env ]; then
    cp .env.example .env
    echo "(.env creado a partir de .env.example)"
fi
ejecutar <<'CMD'
grep -vE '^\s*(#|$)' .env
CMD
HOST_DATA_DIR=$(grep -E '^HOST_DATA_DIR=' .env | cut -d= -f2- | sed 's/[[:space:]]*#.*//')
HOST_DATA_DIR="${HOST_DATA_DIR:-./data/raw}"

# ---------------------------------------------------------------------------
titulo "3.3 Preparar el volumen (el contenedor escribe como UID 10001)"
mkdir -p "$HOST_DATA_DIR"
if ls "$HOST_DATA_DIR"/*.jsonl >/dev/null 2>&1; then
    if [ "$LIMPIAR" = si ]; then
        ejecutar <<'CMD'
sudo rm -f "$HOST_DATA_DIR"/*.jsonl "$HOST_DATA_DIR"/manifiesto_receptor.json
CMD
    else
        echo "ERROR: $HOST_DATA_DIR ya contiene archivos .jsonl de una corrida anterior."
        echo "Sumarian al conteo. Vuelva a ejecutar con:  bash lab/parte3.sh --limpiar"
        exit 1
    fi
fi
docker compose down >/dev/null 2>&1
ejecutar <<'CMD'
sudo chown -R 10001:10001 "$HOST_DATA_DIR"
CMD
ejecutar <<'CMD'
ls -ld "$HOST_DATA_DIR"
CMD
# Chequeo explicito: en Linux el dueno TIENE que quedar en 10001 o el ingestor
# fallara con PermissionError. En un bind mount de Windows (Docker Desktop)
# el sistema de archivos no aplica UIDs: el chown no tiene efecto y tampoco
# hace falta; la prueba con permisos reales esta en lab/prueba_permisos.sh.
DUENO=$(stat -c '%u' "$HOST_DATA_DIR" 2>/dev/null)
if [ "$DUENO" = 10001 ]; then
    echo "OK: $HOST_DATA_DIR pertenece al UID 10001"
elif [ "$(uname -s)" = Linux ]; then
    echo "ERROR: $HOST_DATA_DIR pertenece al UID $DUENO, no al 10001; el ingestor no podra escribir."
    exit 1
else
    echo "AVISO: $(uname -s) con Docker Desktop: $HOST_DATA_DIR es una carpeta de Windows y el"
    echo "bind mount no aplica UIDs (dueno visto: $DUENO). Prueba con permisos Linux reales:"
    echo "bash lab/prueba_permisos.sh"
fi

# ---------------------------------------------------------------------------
titulo "3.4 Validar el YAML (interpola el .env), construir y levantar"
ejecutar <<'CMD'
docker compose config
CMD
if [ "${SIN_BUILD:-0}" != 1 ]; then
    ejecutar <<'CMD'
docker compose build
CMD
fi
T0=$(ahora)
ejecutar <<'CMD'
docker compose up -d
CMD
ejecutar <<'CMD'
docker compose ps
CMD

titulo "3.4 Red privada: los 2 contenedores, sus IPs y la resolucion por nombre"
ejecutar <<'CMD'
docker network inspect red-datos-lab --format '{{range .Containers}}{{.Name}} -> {{.IPv4Address}}{{"\n"}}{{end}}'
CMD
if ! ejecutar <<'CMD'
docker compose exec simulador-puerto python -c "import socket; print(socket.gethostbyname('ingestor-tcp'))"
CMD
then
    echo "(el simulador ya termino; se resuelve desde un contenedor efimero en la misma red)"
    ejecutar <<'CMD'
docker compose run --rm --no-deps simulador-puerto python -c "import socket; print(socket.gethostbyname('ingestor-tcp'))"
CMD
fi
ejecutar <<'CMD'
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}'
CMD

# ---------------------------------------------------------------------------
titulo "3.5 Durante la ingesta: el archivo crece en el host, en vivo"
echo "(equivale a: watch -n 2 'ls -lh data/raw/ && wc -l data/raw/*.jsonl')"
while [ -n "$(docker ps -q -f name=^simulador-puerto$)" ]; do
    echo
    echo "--- $(date +%T)"
    ls -lh "$HOST_DATA_DIR" | grep -E 'jsonl|total'
    wc -l "$HOST_DATA_DIR"/*.jsonl 2>/dev/null | tail -n 1
    docker stats --no-stream --format '{{.Name}}: CPU {{.CPUPerc}}  MEM {{.MemUsage}}' 2>/dev/null
    sleep 3
done
CODIGO_SIM=$(docker wait simulador-puerto)
T1=$(ahora)

# ---------------------------------------------------------------------------
titulo "3.5 Al terminar el simulador (codigo de salida $CODIGO_SIM, $(dif "$T0" "$T1") s)"
ejecutar <<'CMD'
docker compose ps -a
CMD
ejecutar <<'CMD'
wc -l data/raw/*.jsonl
CMD
ejecutar <<'CMD'
du -sh data/raw/
CMD
ejecutar <<'CMD'
head -n 2 data/raw/*.jsonl
CMD
ejecutar <<'CMD'
docker compose logs --no-log-prefix simulador-puerto | tail -n 3
CMD
ejecutar <<'CMD'
docker compose logs ingestor-tcp | tail -n 12
CMD
ejecutar <<'CMD'
head -n 9 data/raw/manifiesto_receptor.json
CMD

# ---------------------------------------------------------------------------
titulo "3.5 Cierre limpio y prueba definitiva de persistencia"
ejecutar <<'CMD'
docker compose stop
CMD
ejecutar <<'CMD'
docker inspect ingestor-tcp --format 'ingestor-tcp ExitCode={{.State.ExitCode}}'
CMD
ejecutar <<'CMD'
docker compose logs --no-log-prefix ingestor-tcp | tail -n 2
CMD
ejecutar <<'CMD'
docker compose down
CMD
ejecutar <<'CMD'
docker compose ps -a
CMD
echo "(sin contenedores)"
ejecutar <<'CMD'
ls -lh data/raw/
CMD
ejecutar <<'CMD'
wc -l data/raw/*.jsonl | tail -n 1
CMD
echo "Los datos SIGUEN en el host despues de destruir los contenedores y la red."

if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    titulo "Validacion completa del dataset (todas las lineas, esquema campo a campo)"
    ejecutar <<'CMD'
python3 -m bench.validar data/raw --profundo
CMD
fi
echo
echo "Evidencia completa en lab/evidencias/parte3.txt"
