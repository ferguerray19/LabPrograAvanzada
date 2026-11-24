#!/usr/bin/env bash
# ============================================================================
#  Prueba de permisos del bind mount con un sistema de archivos Linux REAL
#
#    bash lab/prueba_permisos.sh
#
#  En Docker Desktop, un bind mount de una carpeta de Windows (C:\...) no
#  aplica UID ni permisos POSIX: cualquier UID del contenedor puede escribir.
#  Por eso ahi el `chown 10001:10001 data/raw` no se pone a prueba. Este
#  script lo prueba contra un directorio en un sistema de archivos Linux
#  nativo (ext4/overlay), donde los permisos SI se aplican:
#
#    A) carpeta de datos de root, 755, SIN chown -> el ingestor (UID 10001)
#       debe fallar con PermissionError y el simulador no debe arrancar.
#    B) la misma carpeta CON chown -R 10001:10001 -> la ingesta completa.
#
#  La carpeta se crea y se manipula SOLO con contenedores auxiliares, asi que
#  la ruta la resuelve el daemon de Docker:
#    - Linux / WSL2 con Docker Engine propio: es una ruta del host.
#    - Docker Desktop (Windows/macOS): es una ruta de la VM Linux de Docker,
#      con su propio sistema de archivos Linux (no la unidad C:).
#  Salida en lab/evidencias/permisos_linux.txt.
#
#  Opcional: BASE=<ruta absoluta Linux> (por defecto /var/tmp/lab2-permisos),
#  EVENTOS=<n> (por defecto 200000; la prueba es de permisos, no de volumen).
# ============================================================================
export MSYS_NO_PATHCONV=1          # Git Bash: no reescribir /var/tmp como C:\...
source "$(dirname "$0")/_comun.sh"
registrar permisos_linux.txt

BASE="${BASE:-/var/tmp/lab2-permisos}"
EVENTOS="${EVENTOS:-200000}"
AUX="docker run --rm -v $BASE:/w python:3.12-slim"

[ -f .env ] || cp .env.example .env
docker compose down >/dev/null 2>&1

ejecutar <<'CMD'
docker version --format 'Cliente {{.Client.Version}} / Engine {{.Server.Version}}'
CMD
echo "BASE=\"$BASE\"   # carpeta en el sistema de archivos Linux de la VM de Docker"
echo "EVENTOS=\"$EVENTOS\""
echo "AUX=\"$AUX\"   # contenedor auxiliar con la carpeta Linux montada en /w"

titulo "Preparacion: carpeta de datos en un sistema de archivos Linux nativo"
$AUX sh -c 'rm -rf /w/raw' >/dev/null 2>&1
ejecutar <<'CMD'
$AUX sh -c 'mkdir -p /w/raw && chmod 755 /w/raw && df -T /w | tail -n 1 && ls -lnd /w/raw'
CMD
echo "(dueno UID 0, permisos 755: el UID 10001 del contenedor NO puede escribir)"

# ---------------------------------------------------------------------------
titulo "A) SIN chown: el ingestor corre como UID 10001 y la carpeta es de root"
ejecutar <<'CMD'
$AUX ls -lnd /w/raw
CMD
ejecutar <<'CMD'
HOST_DATA_DIR=$BASE/raw TOTAL_EVENTOS=$EVENTOS docker compose up -d --no-build 2>&1 | tail -n 4
CMD
ejecutar <<'CMD'
docker compose ps -a --format 'table {{.Name}}\t{{.Status}}'
CMD
ejecutar <<'CMD'
docker compose logs --no-log-prefix ingestor-tcp 2>&1 | grep -E 'ERROR|escuchando' | head -n 2
CMD
ejecutar <<'CMD'
docker inspect ingestor-tcp --format 'ingestor-tcp RestartCount={{.RestartCount}} ExitCode={{.State.ExitCode}}'
CMD
ejecutar <<'CMD'
$AUX ls -ln /w/raw
CMD
echo "(sin archivos: no se escribio nada)"
docker compose down >/dev/null 2>&1

# ---------------------------------------------------------------------------
titulo "B) CON chown -R 10001:10001: el mismo stack completa la ingesta"
ejecutar <<'CMD'
$AUX sh -c 'chown -R 10001:10001 /w/raw && ls -lnd /w/raw'
CMD
ejecutar <<'CMD'
HOST_DATA_DIR=$BASE/raw TOTAL_EVENTOS=$EVENTOS docker compose up -d --no-build 2>&1 | tail -n 2
CMD
SIM=$(docker wait simulador-puerto 2>/dev/null)
echo
echo "simulador-puerto termino con codigo $SIM"
ejecutar <<'CMD'
docker compose logs --no-log-prefix simulador-puerto 2>&1 | tail -n 1
CMD
ejecutar <<'CMD'
$AUX sh -c 'ls -ln /w/raw && cat /w/raw/*.jsonl | wc -l'
CMD
echo "(los archivos pertenecen al UID/GID 10001: los escribio appuser)"
docker compose down >/dev/null 2>&1

$AUX sh -c 'rm -rf /w/raw' >/dev/null 2>&1
echo
echo "Evidencia completa en lab/evidencias/permisos_linux.txt"
