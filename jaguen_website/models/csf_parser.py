"""Lee el texto de una Constancia de Situacion Fiscal (CSF) del SAT y la compara con lo que capturo el cliente.
Sin dependencias de Odoo para poder probarlo solo."""
import difflib
import io
import logging
import re
import unicodedata

_logger = logging.getLogger(__name__)

LEGAL = re.compile(r'\b(S\.? ?A\.? ?P\.? ?I\.?|S\.? ?DE ?R\.? ?L\.?|S\.? ?A\.?|S\.? ?C\.?|A\.? ?C\.?|S\.? ?A\.? ?S\.?|DE|C\.? ?V\.?|DE C V|CV|SA|SAS|SC|AC|SAPI|MI|RL|CAPITAL VARIABLE|VARIABLE|CAPITAL)\b')

# claves de regimen fiscal del SAT -> texto que aparece en la CSF
REGIMEN = {
    '601': 'general de ley personas morales', '603': 'personas morales con fines no lucrativos',
    '605': 'sueldos y salarios', '606': 'arrendamiento', '607': 'enajenacion o adquisicion de bienes',
    '608': 'demas ingresos', '610': 'residentes en el extranjero', '611': 'ingresos por dividendos',
    '612': 'personas fisicas con actividades empresariales y profesionales', '614': 'ingresos por intereses',
    '615': 'obtencion de premios', '616': 'sin obligaciones fiscales', '620': 'sociedades cooperativas de produccion',
    '621': 'incorporacion fiscal', '622': 'actividades agricolas', '623': 'opcional para grupos de sociedades',
    '624': 'coordinados', '625': 'actividades empresariales con ingresos a traves de plataformas',
    '626': 'simplificado de confianza',
}


def norm(txt):
    txt = unicodedata.normalize('NFKD', txt or '')
    txt = ''.join(c for c in txt if not unicodedata.combining(c)).upper()
    return re.sub(r'\s+', ' ', re.sub(r'[^A-Z0-9& ]', ' ', txt)).strip()


def clean_name(txt):
    n = norm(txt)
    n = LEGAL.sub(' ', n)
    return re.sub(r'\s+', ' ', n).strip()


def parse(text):
    """Devuelve dict con rfc, nombre, cp, regimenes (lista) o {} si no parece una CSF."""
    t = text.replace('\r', '')
    if 'CONSTANCIA DE SITUACI' not in norm(t).replace(' ', ' ') and 'SITUACION FISCAL' not in norm(t):
        return {}
    out = {}
    m = re.search(r'RFC:\s*([A-ZÑ&0-9]{12,13})', t)
    if m:
        out['rfc'] = m.group(1)
    m = re.search(r'Denominaci[oó]n/Raz[oó]n Social:\s*(.+)', t)
    if m:
        nombre = m.group(1)
        nombre = re.split(r'\s{3,}', nombre.strip())[0]
        out['nombre'] = nombre.strip()
    else:
        parts = []
        for lab in ('Nombre (s)', 'Primer Apellido', 'Segundo Apellido'):
            mm = re.search(re.escape(lab) + r':\s*(.+)', t)
            if mm:
                parts.append(re.split(r'\s{3,}', mm.group(1).strip())[0])
        if parts:
            out['nombre'] = ' '.join(parts)
    m = re.search(r'C[oó]digo Postal:\s*(\d{5})', t)
    if m:
        out['cp'] = m.group(1)
    reg = []
    sec = re.search(r'Reg[ií]menes:(.*?)(?:Obligaciones:|$)', t, re.S)
    if sec:
        for line in sec.group(1).split('\n'):
            line = line.strip()
            if not line or re.match(r'^R[eé]gimen\s+Fecha', line) or line.lower().startswith('régimen fecha'):
                continue
            line = re.split(r'\s{2,}|\s\d{2}/\d{2}/\d{4}', line)[0].strip()
            if len(line) > 8 and not re.match(r'^(R[eé]gimen|Fecha)\s*$', line):
                reg.append(line)
    out['regimenes'] = reg
    return out


def _campo(t, *labels):
    for lab in labels:
        m = re.search(re.escape(lab) + r':[ \t]*(.*)', t)
        if m:
            v = re.split(r'\s{3,}', m.group(1).strip())[0].strip()
            # algunas lineas traen dos etiquetas pegadas: "HERMOSILLO Nombre del Municipio ...: HERMOSILLO"
            v = re.split(r'\s+(?:Nombre del?|N[u\u00fa]mero|C[o\u00f3]digo|Entre Calle|Y Calle|Tipo de|Fecha|Estatus|Correo|Tel)[^:\n]{0,70}:', v)[0].strip()
            if v and not re.match(r'^(Nombre|N[uú]mero|C[oó]digo|Entre|Y Calle|Tipo|Fecha|Estatus|Correo|Tel)\b.*:', v):
                return v
    return ''


def datos_formulario(text):
    """Datos de la CSF listos para llenar el Registrate (el cliente solo los revisa). {} si no se pudo leer."""
    csf = parse(text)
    if not csf or not csf.get('rfc'):
        return {}
    t = text.replace('\r', '')
    reg = ''
    for line in csf.get('regimenes') or []:
        for code, key in REGIMEN.items():
            if key in norm(line).lower():
                reg = code
                break
        if reg:
            break
    out = {
        'rfc': csf['rfc'], 'nombre': csf.get('nombre', ''), 'cp': csf.get('cp', ''),
        'nombre_comercial': _campo(t, 'Nombre Comercial'),
        'calle': _campo(t, 'Nombre de Vialidad'), 'num_ext': _campo(t, 'N\u00famero Exterior', 'Numero Exterior'),
        'num_int': _campo(t, 'N\u00famero Interior', 'Numero Interior'),
        'colonia': _campo(t, 'Nombre de la Colonia'), 'localidad': _campo(t, 'Nombre de la Localidad'),
        'municipio': _campo(t, 'Nombre del Municipio o Demarcaci\u00f3n Territorial', 'Nombre del Municipio o Demarcacion Territorial'),
        'estado': _campo(t, 'Nombre de la Entidad Federativa'), 'regimen': reg,
        'es_persona_fisica': 'Nombre (s)' in t,
    }
    return out


def compare(csf, nombre, rfc, cp, regimen_code):
    """Lista de diferencias legibles entre la CSF y lo capturado. Solo avisa cuando esta seguro."""
    diffs = []
    if csf.get('rfc') and rfc:
        a, b = norm(csf['rfc']).replace(' ', ''), norm(rfc.replace('MX', '', 1) if rfc.upper().startswith('MX') else rfc).replace(' ', '')
        if a != b:
            diffs.append('RFC: el cliente escribio %s y la CSF dice %s' % (rfc, csf['rfc']))
    elif rfc and not csf.get('rfc'):
        diffs.append('No se pudo leer el RFC de la CSF')
    if csf.get('nombre') and nombre:
        a, b = clean_name(csf['nombre']), clean_name(nombre)
        ratio = difflib.SequenceMatcher(None, a, b).ratio()
        contained = bool(a and b and (a in b or b in a))
        if ratio < 0.7 and not contained:
            diffs.append('Nombre: el cliente escribio "%s" y la CSF dice "%s"' % (nombre, csf['nombre']))
    if csf.get('cp') and cp and re.sub(r'\D', '', cp) != csf['cp']:
        diffs.append('Codigo postal: el cliente escribio %s y la CSF dice %s' % (cp, csf['cp']))
    regs = csf.get('regimenes') or []
    if regs and regimen_code in REGIMEN:
        want = REGIMEN[regimen_code]
        if not any(want in norm(r).lower() or want.upper() in norm(r) for r in regs):
            diffs.append('Regimen fiscal: el cliente eligio %s y la CSF dice "%s"' % (regimen_code, '; '.join(regs)))
    return diffs


MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']


def fecha_emision(text):
    """Fecha de emision de la CSF ("Lugar y Fecha de Emision: HERMOSILLO, SONORA A 12 DE MARZO DE 2026") -> (anio, mes, dia) o None."""
    t = norm(text)
    m = re.search(r'\bA (\d{1,2}) DE (ENERO|FEBRERO|MARZO|ABRIL|MAYO|JUNIO|JULIO|AGOSTO|SEPTIEMBRE|SETIEMBRE|OCTUBRE|NOVIEMBRE|DICIEMBRE) (?:DE |DEL )?(\d{4})\b', t)
    if not m:
        return None
    mes = m.group(2).lower().replace('setiembre', 'septiembre')
    return int(m.group(3)), MESES.index(mes) + 1, int(m.group(1))


def parse_opinion(text):
    """Opinion de cumplimiento (32-D): rfc, sentido (POSITIVO/NEGATIVO), fecha (anio, mes, dia) o {} si no lo parece."""
    t = norm(text)
    if 'OPINION DEL CUMPLIMIENTO' not in t and 'OPINION DE CUMPLIMIENTO' not in t:
        return {}
    out = {}
    m = re.search(r'RFC:?\s+(?:Folio\s+)?([A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3})\b', text.replace('\n', ' '))
    if m:
        out['rfc'] = m.group(1)
    m = re.search(r'\b(POSITIVO|NEGATIVO)\b', t)
    if m:
        out['sentido'] = m.group(1)
    m = re.search(r'FECHA Y HORA DE EMISION\s+(\d{1,2}) DE (ENERO|FEBRERO|MARZO|ABRIL|MAYO|JUNIO|JULIO|AGOSTO|SEPTIEMBRE|SETIEMBRE|OCTUBRE|NOVIEMBRE|DICIEMBRE) (?:DE |DEL )?(\d{4})', t)
    if m:
        out['fecha'] = (int(m.group(3)), MESES.index(m.group(2).lower().replace('setiembre', 'septiembre')) + 1, int(m.group(1)))
    return out


def mismo_rfc(a, b):
    def n(x):
        x = re.sub(r'[^A-Z0-9&Ñ]', '', (x or '').upper())
        return x[2:] if x.startswith('MX') and len(x) > 13 else x
    return n(a) == n(b)


def rfc_del_archivo(text, tipo='csf'):
    return (parse(text) if tipo == 'csf' else parse_opinion(text)).get('rfc')


def revisar_archivo(text, hoy, tipo='csf', rfc=None):
    """Valida el texto de una CSF u opinion de cumplimiento recien subida. Devuelve (estado, mensaje):
    ok | unreadable (sin texto: se acepta y se revisa a mano) | notcsf | old | future."""
    nombre = 'constancia' if tipo == 'csf' else 'opinión de cumplimiento'
    liga = ('https://www.sat.gob.mx/portal/public/tramites/constancia-de-situacion-fiscal' if tipo == 'csf'
            else 'https://www.sat.gob.mx/portal/public/tramites/opinion-del-cumplimiento')
    if not (text or '').strip():
        return 'unreadable', 'No pudimos leer la fecha de tu %s (parece escaneada). La revisaremos nosotros.' % nombre
    if tipo == 'csf':
        if not parse(text):
            return 'notcsf', 'Este archivo no parece una Constancia de Situación Fiscal del SAT. Sube el PDF que descargas del SAT: %s' % liga
        f = fecha_emision(text)
    else:
        op = parse_opinion(text)
        if not op:
            return 'notcsf', 'Este archivo no parece la Opinión de Cumplimiento del SAT. Sube el PDF que descargas del SAT: %s' % liga
        f = op.get('fecha')
    rfc_doc = rfc_del_archivo(text, tipo)
    if rfc and rfc_doc and not mismo_rfc(rfc, rfc_doc):
        return 'rfcdiff', ('El RFC de tu %s (%s) no es el que escribiste (%s). Sube el documento de la empresa que estás registrando '
                           'o corrige el RFC.' % (nombre, rfc_doc, rfc.strip().upper()))
    if not f:
        return 'unreadable', 'No pudimos leer la fecha de tu %s. La revisaremos nosotros.' % nombre
    anio, mes, _dia = f
    cur = (hoy.year, hoy.month)
    prev = (hoy.year, hoy.month - 1) if hoy.month > 1 else (hoy.year - 1, 12)
    if (anio, mes) > cur:
        return 'future', 'La fecha de tu %s es posterior a hoy. Revisa que sea el archivo correcto.' % nombre
    if (anio, mes) not in (cur, prev):
        return 'old', ('Tu %s es de %s %d. Necesitamos una del mes en curso (%s) o del mes anterior (%s). '
                       'Descárgala actualizada aquí y vuelve a subirla: %s' % (
                           nombre, MESES[mes - 1], anio, MESES[cur[1] - 1], MESES[prev[1] - 1], liga))
    return 'ok', '%s vigente.' % nombre.capitalize()


def detalle(text, tipo, rfc_form=None):
    """Lo que el sistema leyo del documento, en una frase, para que Ale ayude (ella no ve el archivo)."""
    if not (text or '').strip():
        return 'El archivo no tiene texto legible (parece foto o escaneado).'
    doc = parse(text) if tipo == 'csf' else parse_opinion(text)
    if not doc:
        return 'El archivo no parece %s del SAT.' % ('una Constancia de Situación Fiscal' if tipo == 'csf' else 'una Opinión de cumplimiento')
    bits = []
    if doc.get('rfc'):
        bits.append('el RFC del documento es %s%s' % (doc['rfc'], (' y el que escribió en el formulario es %s' % rfc_form.strip().upper()) if rfc_form else ''))
    f = fecha_emision(text) if tipo == 'csf' else doc.get('fecha')
    if f:
        bits.append('la fecha de emisión del documento es %s %d' % (MESES[f[1] - 1], f[0]))
    return ('Lo que leyó el sistema: ' + '; '.join(bits) + '.') if bits else ''


def pdf_text(data):
    """Texto de las primeras paginas de un PDF ('' si es imagen o no se puede leer)."""
    try:
        try:
            from pypdf import PdfReader
        except ImportError:
            from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return '\n'.join((pg.extract_text() or '') for pg in list(reader.pages)[:4])
    except Exception:
        _logger.exception('CSF: no se pudo leer el PDF')
        return ''
