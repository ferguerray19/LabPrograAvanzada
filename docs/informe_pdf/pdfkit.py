"""Utilidades para armar el informe del Lab 2 con reportlab.

Todo bloque de terminal del informe se transcribe de un archivo de
lab/evidencias/. `Evidencia.ubicar` verifica que cada linea del bloque exista
en el archivo, en orden, y devuelve el rango de lineas que se cita en el pie
("Fuente: archivo, lineas a-b"). Si una linea no aparece, el build falla.
"""
import re
import textwrap
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, Paragraph, Spacer, Table,
                                TableStyle, XPreformatted)

F = "C:/Windows/Fonts/"
pdfmetrics.registerFont(TTFont("Cal", F + "calibri.ttf"))
pdfmetrics.registerFont(TTFont("Cal-B", F + "calibrib.ttf"))
pdfmetrics.registerFont(TTFont("Cal-I", F + "calibrii.ttf"))
pdfmetrics.registerFont(TTFont("Cal-BI", F + "calibriz.ttf"))
pdfmetrics.registerFont(TTFont("Mono", F + "consola.ttf"))
pdfmetrics.registerFont(TTFont("Mono-B", F + "consolab.ttf"))
registerFontFamily("Cal", normal="Cal", bold="Cal-B", italic="Cal-I", boldItalic="Cal-BI")
registerFontFamily("Mono", normal="Mono", bold="Mono-B", italic="Mono", boldItalic="Mono-B")

ACENTO = colors.HexColor("#1F4E79")
GRIS = colors.HexColor("#5A5A5A")
FONDO_T = colors.HexColor("#1E1E1E")
TEXTO_T = colors.HexColor("#E6E6E6")
BORDE = colors.HexColor("#BFBFBF")
CAB = colors.HexColor("#DCE6F1")

ANCHO = A4[0] - 2 * 18 * mm

S = {
    "body": ParagraphStyle("body", fontName="Cal", fontSize=10.5, leading=14, spaceAfter=5),
    "small": ParagraphStyle("small", fontName="Cal", fontSize=9, leading=11.5, textColor=GRIS, spaceAfter=4),
    "h1": ParagraphStyle("h1", fontName="Cal-B", fontSize=16, leading=20, textColor=ACENTO,
                         spaceBefore=6, spaceAfter=8, keepWithNext=1),
    "h2": ParagraphStyle("h2", fontName="Cal-B", fontSize=12.5, leading=16, textColor=ACENTO,
                         spaceBefore=8, spaceAfter=5, keepWithNext=1),
    "cap": ParagraphStyle("cap", fontName="Cal-I", fontSize=9, leading=11, textColor=GRIS,
                          spaceBefore=2, spaceAfter=1),
    "src": ParagraphStyle("src", fontName="Cal", fontSize=8, leading=10, textColor=GRIS, spaceAfter=8),
    "title": ParagraphStyle("title", fontName="Cal-B", fontSize=24, leading=29, textColor=ACENTO, alignment=TA_CENTER),
    "subtitle": ParagraphStyle("subtitle", fontName="Cal", fontSize=13, leading=17, textColor=GRIS, alignment=TA_CENTER),
    "cell": ParagraphStyle("cell", fontName="Cal", fontSize=9.5, leading=12),
    "cellb": ParagraphStyle("cellb", fontName="Cal-B", fontSize=9.5, leading=12),
    "code": ParagraphStyle("code", fontName="Mono", fontSize=7.4, leading=9.2, textColor=colors.black),
    "term": ParagraphStyle("term", fontName="Mono", fontSize=7.2, leading=8.9, textColor=TEXTO_T),
    "bullet": ParagraphStyle("bullet", fontName="Cal", fontSize=10.5, leading=14, leftIndent=12, bulletIndent=2, spaceAfter=2),
}

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
TROZO = 45


def limpiar(txt):
    return ANSI.sub("", txt).replace("\r", "")


def P(texto, estilo="body"):
    return Paragraph(texto, S[estilo])


def M(texto):
    """Texto en monoespaciada dentro de un Paragraph."""
    return f"<font face='Mono'>{texto}</font>"


def bullets(items):
    return [Paragraph(t, S["bullet"], bulletText="•") for t in items]


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _envolver(texto, ancho):
    out = []
    for linea in texto.expandtabs(8).splitlines():
        if len(linea) <= ancho:
            out.append(linea)
        else:
            partes = textwrap.wrap(linea, ancho, break_long_words=True,
                                   replace_whitespace=False, drop_whitespace=False)
            out.append(partes[0])
            out += ["  " + p for p in partes[1:]]
    return out


class Evidencia:
    """Un archivo de lab/evidencias/, partido en secciones por los banners ===."""

    def __init__(self, ruta, raiz):
        self.ruta = Path(ruta)
        self.rel = self.ruta.relative_to(raiz).as_posix()
        self.texto = limpiar(self.ruta.read_text(encoding="utf-8", errors="replace"))
        self.lineas = self.texto.split("\n")
        partes = re.split(r"\n=+\n  (.+)\n=+\n", "\n" + self.texto)
        self.sec = {"_cabecera": partes[0].strip("\n")}
        for i in range(1, len(partes) - 1, 2):
            self.sec[partes[i].strip()] = partes[i + 1].strip("\n")

    def s(self, prefijo):
        for k, v in self.sec.items():
            if k.startswith(prefijo):
                return v
        raise KeyError(f"{self.rel}: no hay seccion '{prefijo}'")

    def ubicar(self, bloque):
        """Rango (a, b) de lineas del archivo que contiene, en orden, todas las
        lineas no vacias del bloque. Falla si alguna no esta."""
        buscadas = [l.rstrip() for l in bloque.split("\n") if l.strip() and l.strip() != "[...]"]
        norm = [l.rstrip() for l in self.lineas]
        mejor = None
        # Se prueba cada aparicion de la primera linea y se queda el rango mas
        # corto que contiene todas las lineas en orden: asi un comando que se
        # repite en el archivo no desplaza la cita a otra seccion.
        for ini in (k for k, l in enumerate(norm) if l == buscadas[0]):
            i = ini
            for linea in buscadas:
                while i < len(norm) and norm[i] != linea:
                    i += 1
                if i == len(norm):
                    break
                i += 1
            else:
                if mejor is None or i - ini < mejor[1] - mejor[0]:
                    mejor = (ini + 1, i)
        if mejor is None:
            raise ValueError(f"{self.rel}: el bloque no esta en el archivo: {buscadas[0]!r}")
        return mejor

    def fuente(self, bloque):
        a, b = self.ubicar(bloque)
        return f"Fuente: {self.rel}, líneas {a}–{b}" if a != b else f"Fuente: {self.rel}, línea {a}"

    def buscar(self, patron, grupo=1, flags=re.M):
        m = re.search(patron, self.texto, flags)
        if not m:
            raise ValueError(f"{self.rel}: no se encontro /{patron}/")
        return m.group(grupo)

    def todos(self, patron, flags=re.M):
        return re.findall(patron, self.texto, flags)


def _caja(html_lineas, estilo, fondo, borde=None):
    xp = XPreformatted("\n".join(html_lineas), S[estilo])
    t = Table([[xp]], colWidths=[ANCHO])
    st = [
        ("BACKGROUND", (0, 0), (-1, -1), fondo),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if borde:
        st.append(("BOX", (0, 0), (-1, -1), 0.5, borde))
    t.setStyle(TableStyle(st))
    return t


def terminal(texto, pie, ev=None, ancho_chars=112):
    """Bloque estilo terminal con el pie DEBAJO y la fuente citada.
    `ev` es la Evidencia de la que sale el texto (se verifica)."""
    texto = limpiar(texto).rstrip("\n")
    fuente = ev.fuente(texto) if ev is not None else None
    html = []
    for l in _envolver(texto, ancho_chars):
        e = _esc(l)
        if l.startswith("$ "):
            e = f'<font color="#8FD18F"><b>{e}</b></font>'
        html.append(e)
    trozos = [html[i:i + TROZO] for i in range(0, len(html), TROZO)]
    cajas = [_caja(t, "term", FONDO_T) for t in trozos]
    cola = [cajas[-1], Paragraph(pie, S["cap"])]
    if fuente:
        cola.append(Paragraph(fuente, S["src"]))
    else:
        cola.append(Spacer(1, 6))
    return cajas[:-1] + [KeepTogether(cola)]


def codigo(texto, pie=None, ancho_chars=110):
    lineas = [_esc(l) for l in _envolver(texto.rstrip("\n"), ancho_chars)]
    trozos = [lineas[i:i + TROZO] for i in range(0, len(lineas), TROZO)]
    res = [_caja(t, "code", colors.HexColor("#F5F5F5"), BORDE) for t in trozos]
    res.append(Paragraph(pie, S["src"]) if pie else Spacer(1, 6))
    return res


def tabla(filas, anchos=None, cabecera=True, negrita_ultima=False):
    datos = []
    for i, f in enumerate(filas):
        est = "cellb" if (cabecera and i == 0) or (negrita_ultima and i == len(filas) - 1) else "cell"
        datos.append([c if not isinstance(c, str) else Paragraph(c, S[est]) for c in f])
    if anchos:
        tot = sum(anchos)
        anchos = [ANCHO * a / tot for a in anchos]
    t = Table(datos, colWidths=anchos, repeatRows=1 if cabecera else 0)
    st = [
        ("GRID", (0, 0), (-1, -1), 0.5, BORDE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if cabecera:
        st.append(("BACKGROUND", (0, 0), (-1, 0), CAB))
    t.setStyle(TableStyle(st))
    return [t, Spacer(1, 8)]


def imagen(ruta, pie, fuente, ancho_max=None):
    from PIL import Image as PI
    w, h = PI.open(ruta).size
    ancho = min(ancho_max or ANCHO, ANCHO)
    if w * 0.75 < ancho:              # no agrandar capturas chicas mas alla de ~96 dpi
        ancho = w * 0.75
    esc = ancho / w
    img = Image(str(ruta), width=w * esc, height=h * esc)
    img.hAlign = "LEFT"
    return [KeepTogether([img, Paragraph(pie, S["cap"]), Paragraph(fuente, S["src"])])]


def lineas_renderizadas(texto, estilo="body"):
    """Cuantas lineas ocupa un parrafo al ancho de la pagina (para el limite
    de 15 lineas de la conclusion)."""
    p = Paragraph(texto, S[estilo])
    p.wrap(ANCHO, 10000)
    return len(p.blPara.lines)


def fmt(x, dec=1):
    """Numero con coma decimal y punto de miles, estilo es-CL."""
    s = f"{x:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")
