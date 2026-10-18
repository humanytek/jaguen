"""Reglas de Javier para sugerir una equivalencia (docs/DECISIONES.md, 7q). Funciones puras, sin Odoo.

Una equivalencia solo se sugiere si cuadran las cuatro: marca, descripción, código y precio. Si algo no cuadra no es el
mismo producto. Cada regla devuelve True / False, o None si falta el dato para juzgarla (None nunca cuenta como acierto).
"""
import difflib
import re
import unicodedata

PRICE_TOLERANCE = 0.20
MIN_SHARED_WORDS = 2
MIN_SHARED_RATIO = 0.30
CODE_SIMILARITY = 0.80
STOPWORDS = set("de del la las el los en con para por y a al un una o e x mm pza pieza piezas pzas".split())


def norm_code(value):
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def words(text):
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)
    text = re.sub(r"(\d)([a-z])", r"\1 \2", text)
    text = re.sub(r"([a-z])(\d)", r"\1 \2", text)
    out = set()
    for w in re.findall(r"[a-z0-9]+", text):
        if w in STOPWORDS or len(w) < 2 and not w.isdigit():
            continue
        out.add(w[:-1] if len(w) > 4 and w.endswith("s") else w)
    return out


def brand_ok(brand, our_name):
    b = norm_code(brand)
    if not b:
        return None
    return b in norm_code(our_name)


def description_ok(our_texts, provider_description, brand="", code=""):
    ours = words(" ".join(t for t in our_texts if t))
    theirs = words(provider_description)
    if not ours or not theirs:
        return None, 0
    shared = len(ours & theirs)
    ratio = shared / min(len(ours), len(theirs))
    return (shared >= MIN_SHARED_WORDS and ratio >= MIN_SHARED_RATIO), shared


def code_ok(provider_code, provider_sku, provider_description, our_codes):
    """Código parecido, no idéntico: igual, uno contiene al otro, aparece completo en la descripción del proveedor, o
    se parece ≥ 80 %."""
    theirs = [norm_code(c) for c in (provider_code, provider_sku) if norm_code(c)]
    ours = [norm_code(c) for c in our_codes if norm_code(c)]
    if not theirs or not ours:
        return None
    desc = norm_code(provider_description)
    for t in theirs:
        for o in ours:
            if t == o:
                return True
            if min(len(t), len(o)) >= 4 and (t in o or o in t):
                return True
            if len(o) >= 6 and o in desc:
                return True
            if min(len(t), len(o)) >= 4 and difflib.SequenceMatcher(None, t, o).ratio() >= CODE_SIMILARITY:
                return True
    return False


def price_ok(cost_odoo, cost_provider_raw, multiplier=1.0):
    if not cost_odoo or not cost_provider_raw:
        return None
    ours = cost_provider_raw * (multiplier or 1.0)
    return abs(ours - cost_odoo) / cost_odoo <= PRICE_TOLERANCE


def _shared_model_token(our_texts, provider_description):
    """Número de modelo (letras y dígitos juntos, 4+ caracteres) que aparece en nuestros textos y en la descripción."""
    def tokens(text):
        return {t for t in re.findall(r"[A-Z0-9]+", re.sub(r"[-_/ ]", " ", (text or "").upper()))
                if len(t) >= 4 and any(c.isdigit() for c in t) and any(c.isalpha() for c in t)}
    ours = set()
    for t in our_texts:
        ours |= tokens(t)
    return bool(ours & tokens(provider_description))


def evaluate(our_name, our_texts, our_codes, provider_code, provider_sku, provider_description, brand,
             cost_odoo, cost_provider_raw, multiplier, published=True):
    desc, shared = description_ok(list(our_texts) + [our_name], provider_description, brand, provider_sku)
    checks = {
        "marca": brand_ok(brand, our_name),
        "descripcion": desc,
        "codigo": code_ok(provider_code, provider_sku, provider_description, our_codes),
        "precio": price_ok(cost_odoo, cost_provider_raw, multiplier),
    }
    failed = [k for k, v in checks.items() if v is False]
    if failed == ["marca"] and _shared_model_token(list(our_texts) + [our_name], provider_description):
        # el proveedor a veces pone mal la marca en su campo (tóner Samsung con marca HP): si código, descripción y
        # precio cuadran y ambos textos traen el mismo número de modelo (D111S), es el mismo producto
        failed = []
    if failed == ["precio"] and not published:
        # un producto sin publicar no tiene el costo al día en Odoo: la diferencia de precio no lo descarta
        failed = []
    unknown = [k for k, v in checks.items() if v is None]
    verdict = "no" if failed else ("sin_dato" if unknown else "si")
    return {"checks": checks, "failed": failed, "unknown": unknown, "verdict": verdict, "shared": shared}
