#!/usr/bin/env bash
# ============================================================================
#  Parte 1 en Docker Desktop (Windows + Git Bash)
#
#    bash lab/parte1_windows.sh
#
#  Misma secuencia que lab/parte1.sh, pero la "vista desde el host" se toma
#  dentro de la VM Linux de Docker Desktop (la guia pide no hacerlo desde
#  PowerShell): un contenedor privilegiado con --pid=host ve el /proc de la
#  VM, que es el host real de los contenedores. Salida en
#  lab/evidencias/parte1.txt.
# ============================================================================
export MSYS_NO_PATHCONV=1          # Git Bash no debe reescribir /app/... como C:\...
sudo() { "$@"; }; export -f sudo   # el sudo.exe de Windows abriria UAC
source "$(dirname "$0")/_comun.sh"
registrar parte1.txt

# "host" = la VM Linux de Docker Desktop, vista con --pid=host
HOST="docker run --rm --privileged --pid=host python:3.12-slim"
# red del host = el namespace de red de la VM, donde esta docker0
RED="docker run --rm --net=host alpine"
docker pull -q alpine >/dev/null
BOMB="$(pwd -W)/lab/memory_bomb.py"

docker rm -f lab-cli lab-ns lab-oom lab-oom512 lab-limite >/dev/null 2>&1

titulo "Entorno"
echo "HOST=\"$HOST\"   # shell en la VM Linux de Docker Desktop"
ejecutar <<'CMD'
docker version --format 'Cliente {{.Client.Version}} / Engine {{.Server.Version}} / {{.Server.Platform.Name}}'; docker compose version
CMD
ejecutar <<'CMD'
docker info --format '{{.OperatingSystem}} | kernel {{.KernelVersion}} | {{.NCPU}} CPU | {{.MemTotal}} B RAM | cgroup v{{.CgroupVersion}}'
CMD

# ---------------------------------------------------------------------------
titulo "1.1 Contenedor Python"
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
ejecutar <<'CMD'
docker exec lab-ns readlink /proc/1/ns/pid
CMD

titulo "1.2 b) Vista desde el HOST (VM Linux de Docker Desktop)"
ejecutar <<'CMD'
docker top lab-ns
CMD
PID=$(docker inspect -f '{{.State.Pid}}' lab-ns)
ejecutar <<'CMD'
docker inspect -f '{{.State.Pid}}' lab-ns
CMD
ejecutar <<'CMD'
$HOST sh -c "echo \"PID $PID en el host: \$(tr '\0' ' ' < /proc/$PID/cmdline)\"; grep -E '^(PPid|NSpid)' /proc/$PID/status"
CMD
echo
echo "Identificadores del namespace PID (inodos distintos = aislamiento efectivo):"
ejecutar <<'CMD'
$HOST sh -c "echo contenedor: \$(readlink /proc/$PID/ns/pid); echo host:       \$(readlink /proc/1/ns/pid)"
CMD
ejecutar <<'CMD'
$HOST lsns -p $PID
CMD
echo
echo "CONCLUSION: un unico proceso del kernel con dos identidades: PID 1 dentro"
echo "del contenedor y PID $PID en el host (NSpid muestra ambos)."

# ---------------------------------------------------------------------------
titulo "1.3 IP virtual y red del contenedor"
ejecutar <<'CMD'
docker inspect -f '{{json .NetworkSettings}}' lab-ns | python -m json.tool
CMD
docker inspect -f '{{json .NetworkSettings}}' lab-ns | python -m json.tool \
    > "$EVID/parte1_networksettings.json"
echo "(JSON guardado en lab/evidencias/parte1_networksettings.json)"
ejecutar <<'CMD'
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' lab-ns
CMD
IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' lab-ns)
ejecutar <<'CMD'
docker network inspect bridge --format '{{json .IPAM.Config}}'
CMD
echo
echo "Conectividad hacia el contenedor desde el namespace de red de docker0:"
echo "RED=\"$RED\"   # shell en el namespace de red de la VM, donde vive docker0 (alpine trae ip y ping)"
ejecutar <<'CMD'
$RED ip addr show docker0
CMD
ejecutar <<'CMD'
$RED ping -c 2 $IP
CMD

# ---------------------------------------------------------------------------
titulo "1.4 Cgroups y OOM Killer: provocar el codigo 137 (techo 100 MB, sin swap)"
T0=$(ahora)
ejecutar <<'CMD'
docker run --name lab-oom -m 100m --memory-swap 100m \
  -v "$BOMB:/app/memory_bomb.py:ro" \
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
echo "Traza del kernel (dmesg de la VM), solo las lineas de ESTE contenedor:"
# El dmesg de la VM acumula OOM de otras pruebas (p. ej. lab/limite_ingestor.sh).
# Se filtra por el ID completo del contenedor lab-oom y por el PID que el
# kernel mato dentro de ese cgroup.
CID=$(docker inspect -f '{{.Id}}' lab-oom)
OOM_PID=$($HOST dmesg | grep "task_memcg=/docker/$CID" | sed -n 's/.*,pid=\([0-9]*\),.*/\1/p' | tail -n 1)
ejecutar <<'CMD'
CID=$(docker inspect -f '{{.Id}}' lab-oom); echo "CID=$CID  OOM_PID=$OOM_PID"
CMD
ejecutar <<'CMD'
$HOST dmesg -T | grep -E "oom|Memory cgroup" | grep -E "$CID|process $OOM_PID "
CMD

titulo "1.4 El limite viene del cgroup, no de la aplicacion (cgroup v2)"
ejecutar <<'CMD'
docker run --rm -m 100m python:3.12-slim cat /sys/fs/cgroup/memory.max
CMD
echo "# 104857600 -> exactamente 100 MiB"
docker run -d --name lab-limite -m 100m python:3.12-slim sleep 60 >/dev/null
sleep 2
ejecutar <<'CMD'
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}' lab-limite
CMD

titulo "1.4 Repeticion con 512 MB: el limite es configuracion, no naturaleza"
T2=$(ahora)
ejecutar <<'CMD'
docker run --name lab-oom512 -m 512m --memory-swap 512m \
  -v "$BOMB:/app/memory_bomb.py:ro" \
  python:3.12-slim python /app/memory_bomb.py | tail -n 3
CMD
T3=$(ahora)
ejecutar <<'CMD'
docker inspect lab-oom512 --format 'OOMKilled={{.State.OOMKilled}} ExitCode={{.State.ExitCode}}'
CMD
echo
echo "Con 100 MB sobrevivio $(dif "$T0" "$T1") s; con 512 MB, $(dif "$T2" "$T3") s."

titulo "Limpieza de la Parte 1"
ejecutar <<'CMD'
docker rm -f lab-ns lab-oom lab-oom512 lab-limite lab-cli 2>/dev/null
CMD
