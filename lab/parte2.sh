#!/usr/bin/env bash
# ============================================================================
#  Parte 2 - Dockerfile optimizado y hardening
#
#    bash lab/parte2.sh
#
#  Mide el contexto de build con y sin .dockerignore, construye v0, v1 y v2
#  en frio, repite el build tras cambiar UNA linea de src/receptor_tcp.py,
#  verifica el hardening y compara `docker stop` con y sin init. Deja la
#  salida en lab/evidencias/parte2.txt y la tabla comparativa (entregable 4)
#  en lab/evidencias/parte2_tabla.md.
#
#  Cada build (en frio y rebuild) se repite REPS veces (3 por defecto) y la
#  tabla informa la MEDIANA. Ademas se informa por separado el tiempo de la
#  capa `pip install` (ejecutada o CACHED) y el tiempo de cada paso del
#  rebuild de v2, sacados de los logs --progress=plain.
#
#  El script SIEMPRE deja src/receptor_tcp.py y .dockerignore como estaban,
#  aunque se interrumpa con Ctrl+C.
#
#  Opcional: DOCKERFILE_V2=<ruta> y EXTRA_BUILD="<flags>" cambian el
#  Dockerfile y los flags del build de v2 (solo para entornos sin acceso a
#  los repositorios de Debian). REPS=<n> cambia las repeticiones.
# ============================================================================
source "$(dirname "$0")/_comun.sh"
registrar parte2.txt

DOCKERFILE_V2="${DOCKERFILE_V2:-Dockerfile}"
EXTRA_BUILD="${EXTRA_BUILD:-}"
REPS="${REPS:-3}"

RESPALDO="$(mktemp -d)"
cp src/receptor_tcp.py "$RESPALDO/receptor_tcp.py"
restaurar() {
    cp "$RESPALDO/receptor_tcp.py" src/receptor_tcp.py
    [ -f "$RESPALDO/dockerignore" ] && mv "$RESPALDO/dockerignore" .dockerignore
    docker rm -f sin-init con-init sin-init-10 con-init-10 probe-timeout sin-init-def >/dev/null 2>&1
    rm -rf "$RESPALDO"
}
trap restaurar EXIT

ejecutar <<'CMD'
docker version --format 'Cliente {{.Client.Version}} / Engine {{.Server.Version}}'
CMD

# ---------------------------------------------------------------------------
titulo "Imagenes base: se descargan ANTES para no medir la descarga como build"
ejecutar <<'CMD'
docker pull -q python:3.12 && docker pull -q python:3.12-slim
CMD

# ---------------------------------------------------------------------------
titulo "2.1 .dockerignore: contexto enviado al daemon, antes y despues"
ejecutar <<'CMD'
du -sh .
CMD
ejecutar <<'CMD'
du -sh data
CMD
# BuildKit recuerda el contexto de la transferencia anterior y en el build
# siguiente envia solo la diferencia. Para medir el contexto COMPLETO se
# descarta antes esa cache (solo la de contexto local, no la de capas).
limpiar_contexto() { docker builder prune -f --filter type=source.local >/dev/null 2>&1; }
echo
echo "--- SIN .dockerignore (se aparta temporalmente) ---"
mv .dockerignore "$RESPALDO/dockerignore"
limpiar_contexto
ejecutar <<'CMD'
docker build --no-cache --progress=plain -t prueba-contexto -f Dockerfile.v0 . 2>&1 | grep -i 'transferring context' | tail -n 1
CMD
ejecutar <<'CMD'
docker images prueba-contexto --format 'tamano de la imagen resultante: {{.Size}}'
CMD
mv "$RESPALDO/dockerignore" .dockerignore
echo
echo "--- CON .dockerignore ---"
limpiar_contexto
ejecutar <<'CMD'
docker build --no-cache --progress=plain -t prueba-contexto -f Dockerfile.v0 . 2>&1 | grep -i 'transferring context' | tail -n 1
CMD
ejecutar <<'CMD'
docker images prueba-contexto --format 'tamano de la imagen resultante: {{.Size}}'
CMD
docker rmi prueba-contexto >/dev/null 2>&1

# ---------------------------------------------------------------------------
# build <tag> <dockerfile> <frio|rebuild> <rep> [flags extra...]
# Muestra el comando, guarda el log completo y deja el tiempo en $SEG.
build() {
    local tag="$1" df="$2" modo="$3" rep="$4"; shift 4
    local nc=""; [ "$modo" = frio ] && nc="--no-cache "
    local log="$EVID/build_${tag#proyecto:}_${modo}_r${rep}.log"
    printf '\n$ time docker build %s-t %s -f %s %s.    # %s, repeticion %s\n' \
        "$nc" "$tag" "$df" "${*:+$* }" "$modo" "$rep"
    local t0 t1
    t0=$(ahora)
    # shellcheck disable=SC2086
    if ! docker build $nc--progress=plain -t "$tag" -f "$df" "$@" . > "$log" 2>&1; then
        tail -n 30 "$log"
        echo "ERROR: fallo el build de $tag (log completo en $log)"
        exit 1
    fi
    t1=$(ahora)
    SEG=$(dif "$t0" "$t1")
    echo "real ${SEG}s   (log: lab/evidencias/$(basename "$log"))"
}

mediana() { printf '%s\n' "$@" | sort -g | awk '{a[NR]=$1} END{ if (NR%2) print a[(NR+1)/2]; else printf "%.1f\n", (a[NR/2]+a[NR/2+1])/2 }'; }

# pasos <log>: nombre de cada paso del build y su resultado (DONE <s> o CACHED)
pasos() {
    awk '
        match($0, /^#[0-9]+ /) {
            id = substr($0, 2, RLENGTH - 2); resto = substr($0, RLENGTH + 1)
            if (!(id in nombre)) { nombre[id] = resto; orden[++n] = id; next }
            if (resto ~ /^DONE [0-9.]+s$/)  res[id] = resto
            else if (resto == "CACHED")    res[id] = "CACHED"
        }
        END { for (i = 1; i <= n; i++) { id = orden[i]; if (id in res)
                  printf "%-8s %s\n", res[id] == "CACHED" ? "CACHED" : substr(res[id], 6), substr(nombre[id], 1, 95) } }
    ' "$1"
}

# capa <log> <patron>: resultado del paso cuyo nombre coincide con el patron
capa() { pasos "$1" | awk -v p="$2" 'index($0, p) { print $1; exit }'; }

titulo "2.2 / 2.4 Builds en frio (--no-cache), $REPS repeticiones"
F0=(); F1=(); F2=()
for r in $(seq 1 "$REPS"); do
    build proyecto:v0 Dockerfile.v0 frio "$r";                         F0+=("$SEG")
    build proyecto:v1 Dockerfile.v1 frio "$r";                         F1+=("$SEG")
    # shellcheck disable=SC2086
    build proyecto:v2 "$DOCKERFILE_V2" frio "$r" $EXTRA_BUILD;         F2+=("$SEG")
done

ejecutar <<'CMD'
docker images proyecto --format 'table {{.Tag}}\t{{.Size}}'
CMD
ejecutar <<'CMD'
docker history proyecto:v2 --format 'table {{.Size}}\t{{.CreatedBy}}' | head -n 12
CMD

# ---------------------------------------------------------------------------
titulo "2.4 Prueba de la cache: cambiar UNA linea de src/receptor_tcp.py, $REPS repeticiones"
R0=(); R1=(); R2=()
for r in $(seq 1 "$REPS"); do
    echo
    echo "\$ echo '# comentario de prueba $r' >> src/receptor_tcp.py"
    echo "# comentario de prueba $r" >> src/receptor_tcp.py
    build proyecto:v0 Dockerfile.v0 rebuild "$r";                      R0+=("$SEG")
    build proyecto:v1 Dockerfile.v1 rebuild "$r";                      R1+=("$SEG")
    # shellcheck disable=SC2086
    build proyecto:v2 "$DOCKERFILE_V2" rebuild "$r" $EXTRA_BUILD;      R2+=("$SEG")
done
cp "$RESPALDO/receptor_tcp.py" src/receptor_tcp.py
echo "(src/receptor_tcp.py restaurado)"

echo
echo "Capa 'pip install' en cada rebuild (segundos si se ejecuto, CACHED si se reutilizo):"
PIP0=(); PIP2=()
for r in $(seq 1 "$REPS"); do
    p0=$(capa "$EVID/build_v0_rebuild_r$r.log" "pip install")
    p1=$(capa "$EVID/build_v1_rebuild_r$r.log" "pip install")
    p2=$(capa "$EVID/build_v2_rebuild_r$r.log" "pip --python")
    echo "  repeticion $r:  v0 ${p0:-?}   v1 ${p1:-?}   v2 ${p2:-?}"
    PIP0+=("${p0%s}"); PIP2+=("$p2")
done

echo
echo "Tiempo de cada paso del rebuild de v2 (repeticion 1, del log --progress=plain):"
pasos "$EVID/build_v2_rebuild_r1.log"
echo
echo "Tiempo de cada paso del rebuild de v0 (repeticion 1):"
pasos "$EVID/build_v0_rebuild_r1.log"

# ---------------------------------------------------------------------------
titulo "2.4 Hardening: usuario sin privilegios y venv"
ejecutar <<'CMD'
docker run --rm --entrypoint sh proyecto:v2 -c 'id && which python'
CMD
ejecutar <<'CMD'
docker run --rm --entrypoint sh proyecto:v0 -c 'id && which python'
CMD
echo
echo "El codigo es de root y appuser no lo puede modificar:"
ejecutar <<'CMD'
docker run --rm --entrypoint sh proyecto:v2 -c 'ls -ld /app/src /app/data; touch /app/src/x'
CMD

# ---------------------------------------------------------------------------
titulo "2.4 Plazo de docker stop que asigna este Docker (sin --stop-timeout)"
ejecutar <<'CMD'
docker run -d --name probe-timeout proyecto:v0
CMD
ejecutar <<'CMD'
docker inspect probe-timeout --format 'StopTimeout={{.Config.StopTimeout}}'
CMD
STOP_DEF=$(docker inspect probe-timeout --format '{{.Config.StopTimeout}}')
ejecutar <<'CMD'
docker rm -f probe-timeout
CMD

# stop_prueba <sufijo> <flags de run>: sin-init<sufijo> (v0) y con-init<sufijo> (v2)
stop_prueba() {
    local suf="$1"; shift
    docker rm -f "sin-init$suf" "con-init$suf" >/dev/null 2>&1
    local f="$*"
    ejecutar <<CMD
docker run -d $f--name sin-init$suf proyecto:v0
CMD
    ejecutar <<CMD
docker run -d $f--name con-init$suf proyecto:v2
CMD
    sleep 3
    ejecutar <<CMD
docker inspect sin-init$suf con-init$suf --format '{{.Name}} StopTimeout={{.Config.StopTimeout}}'
CMD
    local t0 t1
    t0=$(ahora); ejecutar <<CMD
docker stop sin-init$suf
CMD
    t1=$(ahora); T_SIN=$(dif "$t0" "$t1"); echo "real ${T_SIN}s"
    t0=$(ahora); ejecutar <<CMD
docker stop con-init$suf
CMD
    t1=$(ahora); T_CON=$(dif "$t0" "$t1"); echo "real ${T_CON}s"
    ejecutar <<CMD
docker inspect sin-init$suf --format 'ExitCode={{.State.ExitCode}}'
CMD
    ejecutar <<CMD
docker inspect con-init$suf --format 'ExitCode={{.State.ExitCode}}'
CMD
    echo
    echo "Lo que el receptor alcanzo a decir antes de salir:"
    ejecutar <<CMD
docker logs sin-init$suf 2>&1 | tail -n 2
CMD
    ejecutar <<CMD
docker logs con-init$suf 2>&1 | tail -n 2
CMD
    E_SIN=$(docker inspect "sin-init$suf" --format '{{.State.ExitCode}}')
    E_CON=$(docker inspect "con-init$suf" --format '{{.State.ExitCode}}')
}

titulo "2.4 SIGTERM en el PID 1: docker stop sin init (v0) y con init (v2), plazo por defecto"
echo "Quien es el PID 1 en cada uno:"
docker rm -f sin-init con-init >/dev/null 2>&1
docker run -d --name sin-init proyecto:v0 >/dev/null
docker run -d --name con-init proyecto:v2 >/dev/null
sleep 2
ejecutar <<'CMD'
docker exec sin-init cat /proc/1/cmdline | tr '\0' ' '; echo
CMD
ejecutar <<'CMD'
docker exec con-init cat /proc/1/cmdline | tr '\0' ' '; echo
CMD
stop_prueba ""
D_SIN=$T_SIN; D_CON=$T_CON; DE_SIN=$E_SIN; DE_CON=$E_CON

titulo "2.4 Plazo que aplica el daemon sin --stop-timeout (docker events, 3 repeticiones)"
# StopTimeout=<nil> significa que el contenedor no fija un plazo propio y se
# usa el del daemon. docker events muestra cuando el daemon envio SIGTERM (15)
# y cuando se rindio y envio SIGKILL (9): la diferencia es el plazo real.
EVS="$EVID/stop_events_default.txt"
: > "$EVS"
for r in 1 2 3; do
    docker rm -f sin-init-def >/dev/null 2>&1
    docker run -d --name sin-init-def proyecto:v0 >/dev/null
    sleep 2
    TMP_EV="$(mktemp)"
    docker events --filter container=sin-init-def --filter event=kill \
        --format '{{.TimeNano}} signal={{.Actor.Attributes.signal}}' > "$TMP_EV" &
    PID_EV=$!
    sleep 1
    t0=$(ahora)
    docker stop sin-init-def >/dev/null
    t1=$(ahora)
    sleep 1
    kill "$PID_EV" 2>/dev/null; wait "$PID_EV" 2>/dev/null
    PLAZO=$(awk '$2=="signal=15"{a=$1} $2=="signal=9"{b=$1} END{ if (a && b) printf "%.2f", (b-a)/1e9; else print "sin SIGKILL" }' "$TMP_EV")
    CODIGO=$(docker inspect sin-init-def --format '{{.State.ExitCode}}')
    {
        echo "repeticion $r: docker stop sin-init-def (v0, sin --stop-timeout)"
        sed 's/^/  evento: /' "$TMP_EV"
        echo "  plazo SIGTERM->SIGKILL segun el daemon: $PLAZO s | time docker stop: $(dif "$t0" "$t1") s | ExitCode=$CODIGO"
    } | tee -a "$EVS"
    rm -f "$TMP_EV"
done
docker rm -f sin-init-def >/dev/null 2>&1
echo "(eventos guardados en lab/evidencias/stop_events_default.txt)"

titulo "2.4 SIGTERM en el PID 1 con el plazo estandar de 10 s (--stop-timeout 10)"
stop_prueba "-10" "--stop-timeout 10 "

# ---------------------------------------------------------------------------
titulo "2.5 Tabla comparativa (mediciones propias, mediana de $REPS)"
a_mb() {  # "1.61GB" / "179MB" / "950kB" -> MB
    echo "$1" | awk '{ v=$1; u=v; gsub(/[0-9.]/,"",u); gsub(/[A-Za-z]/,"",v);
        f=1; if(u=="GB")f=1000; else if(u=="kB"||u=="KB")f=0.001; else if(u=="B")f=0.000001;
        printf "%.1f", v*f }'
}
T_V0=$(docker images proyecto:v0 --format '{{.Size}}')
T_V1=$(docker images proyecto:v1 --format '{{.Size}}')
T_V2=$(docker images proyecto:v2 --format '{{.Size}}')
MF0=$(mediana "${F0[@]}"); MF1=$(mediana "${F1[@]}"); MF2=$(mediana "${F2[@]}")
MR0=$(mediana "${R0[@]}"); MR1=$(mediana "${R1[@]}"); MR2=$(mediana "${R2[@]}")
MP0=$(mediana "${PIP0[@]}")
RED_T=$(awk -v a="$(a_mb "$T_V0")" -v b="$(a_mb "$T_V2")" 'BEGIN{printf "%+.0f %%", (b-a)/a*100}')
RED_R=$(awk -v a="$MR0" -v b="$MR2" 'BEGIN{ if (a>0) printf "%+.0f %%", (b-a)/a*100; else print "-" }')
lista() { local s; s=$(printf '%s / ' "$@"); echo "${s% / }"; }
{
    echo "| Version | Estrategia | Tamano final | Build en frio (mediana) | Rebuild tras 1 linea (mediana) | Capa pip install en el rebuild |"
    echo "|---|---|---|---|---|---|"
    echo "| v0 | python:3.12 + COPY . . + root | $T_V0 | ${MF0} s | ${MR0} s | se ejecuta (${MP0} s) |"
    echo "| v1 | python:3.12-slim, una etapa, requirements primero | $T_V1 | ${MF1} s | ${MR1} s | CACHED |"
    echo "| v2 | Multi-etapa + venv + tini + usuario 10001 | $T_V2 | ${MF2} s | ${MR2} s | CACHED |"
    echo "| Δ v0→v2 | Reduccion obtenida | ${RED_T} | — | ${RED_R} | — |"
    echo
    echo "Repeticiones (s): frio v0 $(lista "${F0[@]}"), v1 $(lista "${F1[@]}"), v2 $(lista "${F2[@]}");"
    echo "rebuild v0 $(lista "${R0[@]}"), v1 $(lista "${R1[@]}"), v2 $(lista "${R2[@]}")."
    echo
    echo "| Prueba de docker stop | StopTimeout | Tiempo | ExitCode |"
    echo "|---|---|---|---|"
    echo "| sin-init (v0, PID 1 = /bin/sh) | por defecto (${STOP_DEF}) | ${D_SIN} s | ${DE_SIN} |"
    echo "| con-init (v2, PID 1 = tini) | por defecto (${STOP_DEF}) | ${D_CON} s | ${DE_CON} |"
    echo "| sin-init-10 (v0) | 10 | ${T_SIN} s | ${E_SIN} |"
    echo "| con-init-10 (v2) | 10 | ${T_CON} s | ${E_CON} |"
} | tee "$EVID/parte2_tabla.md"
echo
ejecutar <<'CMD'
docker images --format 'table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}' | grep -E 'proyecto|REPOSITORY'
CMD
echo
echo "Evidencia completa en lab/evidencias/parte2.txt y lab/evidencias/parte2_tabla.md"
