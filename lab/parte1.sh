#!/usr/bin/env bash
# ============================================================================
#  Parte 1 - Primeros pasos, inspeccion y OOM Killer
#
#    bash lab/parte1.sh
#
#  Corre los comandos de la guia en orden, los muestra como en una terminal y
#  deja todo en lab/evidencias/parte1.txt. Las capturas del informe se toman
#  de esta salida (entregables 1 y 2).
# ============================================================================
source "$(dirname "$0")/_comun.sh"
registrar parte1.txt

docker rm -f lab-cli lab-ns lab-oom lab-oom512 lab-limite >/dev/null 2>&1

# ---------------------------------------------------------------------------
titulo "1.1 Contenedor Python (lo mismo que la sesion interactiva, en una linea)"
echo "Para la captura interactiva: docker run -it --rm --name lab-cli python:3.12-slim bash"
ejecutar <<'CMD'
docker run --rm --name lab-cli python:3.12-slim bash -c \
  'python --version; pip list 2>/dev/null; grep PRETTY_NAME /etc/os-release; echo "hostname: $(hostname)"'
CMD

# ---------------------------------------------------------------------------
titulo "1.2 Namespaces: el mismo proceso, dos PID distintos"
ejecutar <<'CMD'
docker run -d --name lab-ns python:3.12-slim python -c "import time; time.sleep(3600)"
CMD
sleep 1

titulo "1.2 a) Vista desde DENTRO del contenedor"
ejecutar <<'CMD'
docker exec lab-ns sh -c 'echo "PID 1 = $(cat /proc/1/cmdline | tr "\0" " ")"; echo "PIDs visibles:"; ls /proc | grep -E "^[0-9]+$" | tr "\n" " "; echo'
CMD

titulo "1.2 b) Vista desde el HOST"
requiere_linux "ps / readlink / lsns"
ejecutar <<'CMD'
docker top lab-ns
CMD
PID=$(docker inspect -f '{{.State.Pid}}' lab-ns)
ejecutar <<'CMD'
docker inspect -f '{{.State.Pid}}' lab-ns
CMD
ejecutar <<'CMD'
ps -o pid,ppid,cmd -p $(docker inspect -f '{{.State.Pid}}' lab-ns)
CMD
echo
echo "Identificadores del namespace PID (inodos distintos = aislamiento efectivo):"
ejecutar <<'CMD'
sudo readlink /proc/$(docker inspect -f '{{.State.Pid}}' lab-ns)/ns/pid
CMD
ejecutar <<'CMD'
readlink /proc/self/ns/pid
CMD
if command -v lsns >/dev/null 2>&1; then
    ejecutar <<'CMD'
sudo lsns -p $(docker inspect -f '{{.State.Pid}}' lab-ns)
CMD
else
    echo "(lsns no esta instalado; comparacion de todos los namespaces con readlink)"
    ejecutar <<'CMD'
for ns in pid net mnt uts ipc; do printf '%-4s contenedor=%-20s host=%s\n' "$ns" "$(sudo readlink /proc/$PID/ns/$ns)" "$(readlink /proc/self/ns/$ns)"; done
CMD
fi
echo
echo "CONCLUSION: es un unico proceso del kernel del host con dos identidades:"
echo "PID 1 dentro del contenedor y PID $PID en el host. Solo cambia el"
echo "namespace desde el que se observa."

# ---------------------------------------------------------------------------
titulo "1.3 IP virtual y red del contenedor"
if command -v jq >/dev/null 2>&1; then
    ejecutar <<'CMD'
docker inspect lab-ns | jq '.[0].NetworkSettings'
CMD
    docker inspect lab-ns | jq '.[0].NetworkSettings' > "$EVID/parte1_networksettings.json"
else
    ejecutar <<'CMD'
docker inspect -f '{{json .NetworkSettings}}' lab-ns | python3 -m json.tool
CMD
    docker inspect -f '{{json .NetworkSettings}}' lab-ns | python3 -m json.tool \
        > "$EVID/parte1_networksettings.json"
fi
echo "(JSON guardado en lab/evidencias/parte1_networksettings.json)"
ejecutar <<'CMD'
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' lab-ns
CMD
IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' lab-ns)
ejecutar <<'CMD'
docker network inspect bridge --format '{{json .IPAM.Config}}'
CMD
if command -v ip >/dev/null 2>&1; then
    ejecutar <<'CMD'
ip addr show docker0
CMD
fi
if command -v ping >/dev/null 2>&1; then
    ejecutar <<'CMD'
ping -c 2 $IP
CMD
else
    echo "(ping no esta instalado en el host: instale iputils-ping y repita 'ping -c 2 $IP')"
fi

# ---------------------------------------------------------------------------
titulo "1.4 Cgroups y OOM Killer: provocar el codigo 137 (techo 100 MB, sin swap)"
T0=$(ahora)
ejecutar <<'CMD'
docker run --name lab-oom -m 100m --memory-swap 100m \
  -v "$PWD/lab/memory_bomb.py:/app/memory_bomb.py:ro" \
  python:3.12-slim python /app/memory_bomb.py
CMD
CODIGO=$?
T1=$(ahora)
echo
echo "\$ echo \$?"
echo "$CODIGO"
ejecutar <<'CMD'
docker inspect lab-oom --format \
  'OOMKilled={{.State.OOMKilled}} ExitCode={{.State.ExitCode}} Error={{.State.Error}}'
CMD
echo
echo "Traza del kernel:"
ejecutar <<'CMD'
sudo dmesg -T 2>/dev/null | grep -iE "memory cgroup out of memory|oom-kill|invoked oom-killer" | tail -n 5
CMD

titulo "1.4 El limite viene del cgroup, no de la aplicacion"
ejecutar <<'CMD'
docker run --rm -m 100m python:3.12-slim sh -c \
  'cat /sys/fs/cgroup/memory.max 2>/dev/null || cat /sys/fs/cgroup/memory/memory.limit_in_bytes'
CMD
echo "# 104857600 -> exactamente 100 MiB (cgroup v2: memory.max; v1: memory.limit_in_bytes)"
echo
echo "MEM USAGE / LIMIT de un contenedor vivo con el mismo techo:"
docker run -d --name lab-limite -m 100m python:3.12-slim sleep 60 >/dev/null
sleep 1
ejecutar <<'CMD'
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}' lab-limite
CMD

titulo "1.4 Repeticion con 512 MB: el limite es configuracion, no naturaleza"
T2=$(ahora)
ejecutar <<'CMD'
docker run --name lab-oom512 -m 512m --memory-swap 512m \
  -v "$PWD/lab/memory_bomb.py:/app/memory_bomb.py:ro" \
  python:3.12-slim python /app/memory_bomb.py | tail -n 3
CMD
T3=$(ahora)
ejecutar <<'CMD'
docker inspect lab-oom512 --format 'OOMKilled={{.State.OOMKilled}} ExitCode={{.State.ExitCode}}'
CMD
echo
echo "Con 100 MB sobrevivio $(dif "$T0" "$T1") s; con 512 MB, $(dif "$T2" "$T3") s."

# ---------------------------------------------------------------------------
titulo "Limpieza de la Parte 1"
ejecutar <<'CMD'
docker rm -f lab-ns lab-oom lab-oom512 lab-limite lab-cli 2>/dev/null
CMD
echo
echo "Evidencia completa en lab/evidencias/parte1.txt"
