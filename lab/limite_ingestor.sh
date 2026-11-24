#!/usr/bin/env bash
# ============================================================================
#  Experimento de apoyo a la conclusion (entregable 8): cuanta memoria
#  necesita de verdad el ingestor y que limite conviene darle.
#
#    bash lab/limite_ingestor.sh                  # 1g 256m 64m 32m, 2 M eventos
#    bash lab/limite_ingestor.sh 512m 96m 48m     # otros limites
#    N_PROCESOS=16 bash lab/limite_ingestor.sh 1g # 16 conexiones simultaneas
#
#  Para cada MEM_INGESTOR levanta el stack completo con Compose y registra:
#  si la corrida termino bien, el codigo de salida del simulador, el pico de
#  RSS del proceso Python del receptor (VmHWM) y el pico de memoria del cgroup
#  (que incluye la cache de paginas de los archivos escritos).
#
#  Unidades: todo se guarda CRUDO (bytes del cgroup, kB de /proc) en
#  lab/evidencias/limite_ingestor_crudo.tsv, y la tabla muestra MiB reales
#  (bytes / 1048576, kB / 1024).
#
#  Usa 2.000.000 de eventos y NO data/raw: el receptor trabaja en streaming,
#  su memoria no depende del total. Deja la tabla en
#  lab/evidencias/limite_ingestor.md.
# ============================================================================
source "$(dirname "$0")/_comun.sh"
registrar limite_ingestor.txt

LIMITES=("$@")
[ ${#LIMITES[@]} -eq 0 ] && LIMITES=(1g 256m 64m 32m)
EVENTOS="${EVENTOS:-2000000}"
DIR_PRUEBA="./data/bench_tmp/limite"   # ignorado por git y por .dockerignore

[ -f .env ] || cp .env.example .env
docker compose down >/dev/null 2>&1

TABLA="$EVID/limite_ingestor.md"
CRUDO="$EVID/limite_ingestor_crudo.tsv"
{
    echo "| MEM_INGESTOR (memory.max) | Resultado | Salida simulador | Reinicios | Pico RSS receptor (VmHWM) | Pico del cgroup (memory.peak) |"
    echo "|---|---|---|---|---|---|"
} > "$TABLA"
printf 'MEM_INGESTOR\tmemory.max_B\tmemory.peak_B\tVmHWM_kB\tsock_B\toom_kill\treinicios\tsimulador\tlineas\n' > "$CRUDO"

# Muestreador: corre en un contenedor aparte con --cgroupns=host y lee el
# cgroup del ingestor (/sys/fs/cgroup/docker/<id>) cada 20 ms. No se ejecuta
# DENTRO del ingestor para no cargar su propia memoria al cgroup medido.
read -r -d '' MUESTREADOR <<'PY'
import os, sys, time
d = "/sys/fs/cgroup/docker/" + sys.argv[1]
print("t_s\tmemory.current_B\tmemory.max_B\tsock_B\tanon_B\tfile_B\tevents_max\tevents_oom\tevents_oom_kill", flush=True)
t0 = time.time()
while True:
    try:
        cur = open(d + "/memory.current").read().strip()
        mx = open(d + "/memory.max").read().strip()
        st = dict(l.split() for l in open(d + "/memory.stat"))
        ev = dict(l.split() for l in open(d + "/memory.events"))
        print(f"{time.time()-t0:.3f}\t{cur}\t{mx}\t{st['sock']}\t{st['anon']}\t{st['file']}"
              f"\t{ev['max']}\t{ev['oom']}\t{ev['oom_kill']}", flush=True)
    except (OSError, KeyError):
        pass          # el cgroup no existe todavia o se esta recreando (reinicio)
    time.sleep(0.02)
PY

# resumen_muestreo <tsv>: maximo de memory.current, sock en ese instante,
# maximo de sock, cuantas muestras superaron memory.max y contadores finales.
resumen_muestreo() {
    awk -F'\t' 'NR>1 && $2 ~ /^[0-9]+$/ {
            n++; if ($2 > mc) { mc = $2; sock_mc = $4; t_mc = $1 }
            if ($4 > ms) ms = $4
            if ($3 ~ /^[0-9]+$/ && $2 > $3) { sobre++; if ($4 > sock_sobre) sock_sobre = $4 }
            emax = $7; eoom = $8; ekill = $9 }
        END { printf "  max memory.current=%d B (t=%s s, sock en ese instante=%d B) | max sock=%d B\n", mc, t_mc, sock_mc, ms
              printf "  muestras con memory.current > memory.max: %d (max sock en ellas=%d B)\n", sobre, sock_sobre
              printf "  memory.events al final: max=%s oom=%s oom_kill=%s\n", emax, eoom, ekill }' "$1"
}

mib_b()  { awk -v v="$1" 'BEGIN{ if (v ~ /^[0-9]+$/) printf "%.1f MiB", v/1048576; else print "?" }'; }
mib_kb() { awk -v v="$1" 'BEGIN{ if (v ~ /^[0-9]+$/) printf "%.1f MiB", v/1024;    else print "?" }'; }

for LIM in "${LIMITES[@]}"; do
    titulo "MEM_INGESTOR=$LIM  ($EVENTOS eventos, N_PROCESOS=${N_PROCESOS:-segun .env})"
    sudo rm -rf "$DIR_PRUEBA"
    mkdir -p "$DIR_PRUEBA"
    sudo chown -R 10001:10001 "$DIR_PRUEBA"

    # Primero solo el ingestor, luego el muestreador sobre su cgroup, y recien
    # entonces el simulador: asi el muestreo cubre toda la transferencia.
    export MEM_INGESTOR=$LIM TOTAL_EVENTOS=$EVENTOS HOST_DATA_DIR=$DIR_PRUEBA
    docker compose up -d --no-build ingestor-tcp >/dev/null 2>&1
    CID=$(docker inspect -f '{{.Id}}' ingestor-tcp)
    docker rm -f muestreo >/dev/null 2>&1
    docker run -d --name muestreo --privileged --cgroupns=host python:3.12-slim \
        python -c "$MUESTREADOR" "$CID" >/dev/null
    docker compose up -d --no-build simulador-puerto >/dev/null 2>&1
    SIM=$(docker wait simulador-puerto 2>/dev/null || echo "?")
    sleep 1
    MUESTRA="$EVID/limite_ingestor_muestreo_$LIM.tsv"
    docker logs muestreo > "$MUESTRA" 2>&1
    docker rm -f muestreo >/dev/null 2>&1
    unset MEM_INGESTOR TOTAL_EVENTOS HOST_DATA_DIR
    echo "muestreo durante la corrida ($(($(wc -l < "$MUESTRA") - 1)) muestras cada 20 ms, lab/evidencias/$(basename "$MUESTRA")):"
    resumen_muestreo "$MUESTRA"

    # Todo se lee desde dentro del contenedor ANTES de detenerlo, en crudo:
    #   VmHWM        pico de RSS del Python del receptor (hijo de tini), en kB
    #   memory.max   techo del cgroup en bytes
    #   memory.peak  pico de uso del cgroup en bytes (incluye cache de paginas
    #                y los buffers de los sockets TCP)
    #   sock         bytes de buffers de socket cargados al cgroup ahora
    #   oom_kill     cuantas veces el OOM killer mato un proceso de ESTE cgroup
    HWM_KB=$(docker exec ingestor-tcp sh -c \
        'for p in /proc/[0-9]*; do tr "\0" " " < "$p/cmdline" 2>/dev/null | grep -q "^python .*receptor_tcp" && grep VmHWM "$p/status"; done' \
        2>/dev/null | awk '{print $2}')
    MAX_B=$(docker exec ingestor-tcp cat /sys/fs/cgroup/memory.max 2>/dev/null)
    PICO_B=$(docker exec ingestor-tcp sh -c \
        'cat /sys/fs/cgroup/memory.peak 2>/dev/null || cat /sys/fs/cgroup/memory/memory.max_usage_in_bytes' 2>/dev/null)
    SOCK_B=$(docker exec ingestor-tcp awk '$1=="sock"{print $2}' /sys/fs/cgroup/memory.stat 2>/dev/null)
    OOMK=$(docker exec ingestor-tcp awk '$1=="oom_kill"{print $2}' /sys/fs/cgroup/memory.events 2>/dev/null)
    # Si el kernel mato al receptor, `restart: unless-stopped` ya lo levanto
    # de nuevo (en un cgroup nuevo, con contadores en cero) y State.OOMKilled
    # describe al proceso NUEVO: la huella que queda es el contador de
    # reinicios.
    REINICIOS=$(docker inspect ingestor-tcp --format '{{.RestartCount}}' 2>/dev/null)
    LINEAS=$(cat "$DIR_PRUEBA"/*.jsonl 2>/dev/null | wc -l)

    HWM=$(mib_kb "$HWM_KB")
    PICO=$(mib_b "$PICO_B")
    if [ "$SIM" = 0 ]; then
        RES="OK, $LINEAS eventos"
    else
        RES="FALLA: $LINEAS eventos en disco"
    fi
    echo "resultado: $RES | simulador: $SIM | reinicios: $REINICIOS"
    echo "crudo: memory.max=${MAX_B:-?} B | memory.peak=${PICO_B:-?} B | VmHWM=${HWM_KB:-?} kB | sock=${SOCK_B:-?} B | oom_kill=${OOMK:-?}"
    echo "MiB:   memory.max=$(mib_b "$MAX_B") | memory.peak=$PICO | VmHWM=$HWM"
    if [[ "$MAX_B" =~ ^[0-9]+$ && "$PICO_B" =~ ^[0-9]+$ ]] && [ "$PICO_B" -gt "$MAX_B" ]; then
        echo "ATENCION: memory.peak supera a memory.max en $((PICO_B - MAX_B)) bytes"
    fi
    docker compose logs --no-log-prefix ingestor-tcp 2>/dev/null \
        | grep -E 'escuchando|cerrado|ERROR' | tail -n 5
    if [ "$SIM" != 0 ]; then
        sudo dmesg -T 2>/dev/null | grep -E 'Memory cgroup out of memory: Killed process .*python' | tail -n 1
    fi
    echo "| $LIM ($(mib_b "$MAX_B")) | $RES | $SIM | ${REINICIOS:-?} | $HWM | $PICO |" >> "$TABLA"
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$LIM" "${MAX_B:-?}" "${PICO_B:-?}" "${HWM_KB:-?}" \
        "${SOCK_B:-?}" "${OOMK:-?}" "${REINICIOS:-?}" "$SIM" "$LINEAS" >> "$CRUDO"

    docker compose down >/dev/null 2>&1
done
sudo rm -rf "$DIR_PRUEBA"

titulo "Resumen"
cat "$TABLA"
echo
echo "Valores crudos (lab/evidencias/limite_ingestor_crudo.tsv):"
column -t -s $'\t' "$CRUDO" 2>/dev/null || cat "$CRUDO"
