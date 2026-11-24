#!/usr/bin/env bash
# ============================================================================
#  Linea base NATIVA (sin contenedores) para comparar con la Parte 3
#
#    bash lab/baseline_nativo.sh          # en Linux o WSL2, con python3 >= 3.11
#
#  Corre el mismo receptor TCP y el mismo simulador que Compose, con los
#  mismos parametros del .env (4 workers, 10.000.000 de eventos, lotes de
#  50.000, --arch tcp), pero como procesos normales del sistema, sin Docker.
#  Repite REPS veces (3 por defecto) y deja la salida en
#  lab/evidencias/baseline_nativo.txt.
#
#  En Windows nativo el receptor no corre (asyncio no implementa
#  loop.add_signal_handler en Windows): por eso la linea base se toma en
#  Linux / WSL2 sobre el mismo equipo.
#
#  Opcional: DIR_DATOS=<carpeta> (por defecto una carpeta temporal en el
#  sistema de archivos Linux nativo), REPS=<n>, PUERTO=<n>.
# ============================================================================
source "$(dirname "$0")/_comun.sh"
registrar baseline_nativo.txt

REPS="${REPS:-3}"
PUERTO="${PUERTO:-9019}"
DIR_DATOS="${DIR_DATOS:-$HOME/lab2-baseline}"
PY="${PY:-python3}"

titulo "Entorno de la linea base nativa"
ejecutar <<'CMD'
uname -srm; $PY --version; nproc; free -m | head -n 2
CMD
mkdir -p "$DIR_DATOS"
ejecutar <<'CMD'
df -hT "$DIR_DATOS" | tail -n 1
CMD

for r in $(seq 1 "$REPS"); do
    titulo "Corrida nativa $r de $REPS: receptor + simulador --arch tcp, 4 workers, 10 M eventos"
    rm -f "$DIR_DATOS"/*.jsonl "$DIR_DATOS"/manifiesto_receptor.json
    LOG_RX="$(mktemp)"
    $PY src/receptor_tcp.py --host 127.0.0.1 --port "$PUERTO" --data-dir "$DIR_DATOS" > "$LOG_RX" 2>&1 &
    RX=$!
    for _ in $(seq 1 50); do grep -q escuchando "$LOG_RX" && break; sleep 0.2; done
    ejecutar <<'CMD'
$PY -m src.main --arch tcp --workers 4 --total-events 10000000 --batch-size 50000 \
  --tcp-host 127.0.0.1 --tcp-port $PUERTO --bench-csv "" 2>&1 | tail -n 1
CMD
    kill -TERM "$RX"; wait "$RX"; echo "receptor salio con codigo $?"
    grep -E 'cerrado|apagado limpio' "$LOG_RX" | tail -n 2
    ejecutar <<'CMD'
wc -l "$DIR_DATOS"/*.jsonl | tail -n 1
CMD
    rm -f "$LOG_RX"
done

titulo "Resumen (eventos por segundo que informa el simulador en cada corrida)"
grep -oE '\(([0-9]+) ev/s' "$EVID/baseline_nativo.txt" | tr -d '(' | awk '{print "  " $1 " ev/s"}'
grep -oE '\(([0-9]+) ev/s' "$EVID/baseline_nativo.txt" | tr -d '(' | awk '{print $1}' | sort -n \
    | awk '{a[NR]=$1} END{ if (NR) print "mediana: " (NR%2 ? a[(NR+1)/2] : (a[NR/2]+a[NR/2+1])/2) " ev/s" }'
rm -f "$DIR_DATOS"/*.jsonl "$DIR_DATOS"/manifiesto_receptor.json
