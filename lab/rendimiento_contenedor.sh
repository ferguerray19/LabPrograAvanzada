#!/usr/bin/env bash
# ============================================================================
#  Rendimiento del stack en contenedores: 3 corridas completas
#
#    bash lab/rendimiento_contenedor.sh
#
#  Mismos parametros que la Parte 3 (los del .env: 10.000.000 de eventos,
#  4 procesos, lotes de 50.000, --arch tcp) y los mismos que usa
#  lab/baseline_nativo.sh, para comparar mediana contra mediana. Escribe en
#  una carpeta aparte (data/bench_tmp/rend) para no tocar el dataset de
#  data/raw. Salida en lab/evidencias/rendimiento_contenedor.txt.
# ============================================================================
source "$(dirname "$0")/_comun.sh"
registrar rendimiento_contenedor.txt

REPS="${REPS:-3}"
DIR="./data/bench_tmp/rend"          # ignorado por git y por .dockerignore

[ -f .env ] || cp .env.example .env
docker compose down >/dev/null 2>&1

titulo "Parametros (del .env) y version de Python dentro del contenedor"
ejecutar <<'CMD'
grep -E '^(TOTAL_EVENTOS|N_PROCESOS|BATCH_SIZE|TCP_HOST|TCP_PORT)=' .env | sed 's/[[:space:]]*#.*//'
CMD
ejecutar <<'CMD'
docker run --rm --entrypoint python proyecto/simulador:v2 --version
CMD
echo "(el simulador corre con --arch tcp: ver command: en docker-compose.yml)"

for r in $(seq 1 "$REPS"); do
    titulo "Corrida en contenedores $r de $REPS"
    rm -rf "$DIR"; mkdir -p "$DIR"
    HOST_DATA_DIR=$DIR docker compose up -d --no-build >/dev/null 2>&1
    SIM=$(docker wait simulador-puerto)
    ejecutar <<'CMD'
docker compose logs --no-log-prefix simulador-puerto | grep -E 'tpc: (plan|OK)'
CMD
    echo "simulador-puerto salio con codigo $SIM"
    ejecutar <<'CMD'
cat "$DIR"/*.jsonl | wc -l
CMD
    docker compose down >/dev/null 2>&1
done
rm -rf "$DIR"

titulo "Resumen (eventos por segundo que informa el simulador en cada corrida)"
grep -oE 'OK: [0-9]+ eventos.*\(([0-9]+) ev/s' "$EVID/rendimiento_contenedor.txt" \
    | grep -oE '[0-9]+ ev/s' | awk '{print "  " $1 " ev/s"}'
grep -oE 'OK: [0-9]+ eventos.*\(([0-9]+) ev/s' "$EVID/rendimiento_contenedor.txt" \
    | grep -oE '[0-9]+ ev/s' | awk '{print $1}' | sort -n \
    | awk '{a[NR]=$1} END{ if (NR) print "mediana: " (NR%2 ? a[(NR+1)/2] : (a[NR/2]+a[NR/2+1])/2) " ev/s" }'
