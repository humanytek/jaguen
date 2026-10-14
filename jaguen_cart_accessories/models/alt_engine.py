# -*- coding: utf-8 -*-
"""Motor de productos alternativos de JAGUEN (Python puro, sin Odoo).

Para cada producto publicado calcula dos listas de candidatos:
  * parecidos: ordenados por una formula lineal ajustada con las listas de alternativos que la tienda ya tenia
    (parecido del nombre ponderado por rareza de las palabras, misma categoria / linea, misma marca, medida igual...);
  * complementos: productos que se usan con este (corrector junto a una pluma, puntillas junto a un lapicero,
    cafe junto a una cafetera). Salen de un mapa categoria -> categorias complementarias (data/complement_map.json),
    escogiendo dentro de cada categoria lo mas vendido y de la misma marca.
La tienda arma con ellos los 8 alternativos de cada dia (ver alt_cache.py).
"""
import difflib
import math
import re
import unicodedata
from collections import defaultdict

MISMA = '@MISMA'   # en el mapa: producto de la misma categoria pero de otro tipo (corrector junto a pluma)
POOL = 60          # candidatos que se puntuan con la formula
COMMON_DF = 250    # palabras mas comunes que esto no sirven para buscar candidatos


def norm(text):
    text = unicodedata.normalize('NFD', (text or '').lower())
    return ''.join(c for c in text if unicodedata.category(c) != 'Mn')


def tokens(text):
    return [t for t in re.findall(r'[a-z0-9]+', norm(text)) if len(t) > 1]


class Engine:
    def __init__(self, products, weights, complement_map, popularity=None):
        """products: lista de dicts {id, name, categ_id, categ_name, public_categ_ids}.
        weights: {'cols': [...], 'w': [...], 'b': x}. complement_map: {'Dept / Categoria': ['Dept / Otra', '@MISMA', ...]}.
        popularity: {product_id: unidades vendidas}."""
        self.pop = popularity or {}
        self.w = dict(zip(weights['cols'], weights['w']))
        self.b = weights['b']
        self.P = {}
        df = defaultdict(int)
        for p in products:
            t = tokens(p['name'])
            ts = set(t)
            path = [x.strip() for x in (p.get('categ_name') or '').split('/')]
            nums = [float(x) for x in re.findall(r'\d+(?:\.\d+)?', p['name'])][:4]
            mm = set(re.findall(r'(\d+(?:\.\d+)?)\s*mm', norm(p['name'])))
            self.P[p['id']] = {
                'id': p['id'], 't': t, 'ts': ts, 'brand': t[-1] if t else '',
                'spec': {x for x in ts if re.search(r'\d', x)}, 'nums': nums, 'mm': mm,
                'path': path, 'categ': p.get('categ_id'), 'pc': set(p.get('public_categ_ids') or []),
                'head': t[0] if t else '',
                'dept': (path[1] if path[0] == 'All' and len(path) > 1 else path[0]),
            }
            for x in ts:
                df[x] += 1
        n = len(self.P)
        self.df = df
        self.idf = {x: math.log(n / (1 + c)) + 0.1 for x, c in df.items()}
        self.index = defaultdict(list)
        self.by_categ = defaultdict(list)
        self.by_dept = defaultdict(set)
        for pid, p in self.P.items():
            self.by_categ[p['categ']].append(pid)
            self.by_dept[p['dept']].add(pid)
            for x in p['ts']:
                if df[x] <= COMMON_DF:
                    self.index[x].append(pid)
        # mapa de complementos: nombre de categoria (sin 'All / ') -> ids de categoria
        self.categ_by_name = {}
        for p in products:
            name = (p.get('categ_name') or '')
            if name.startswith('All / '):
                name = name[6:]
            self.categ_by_name[name] = p.get('categ_id')
        self.comp_map = complement_map
        self.name_of_categ = {v: k for k, v in self.categ_by_name.items()}

    # ------------------------------------------------------------ parecido
    def _wjaccard(self, a, b):
        inter = a & b
        if not inter:
            return 0.0
        uni = a | b
        return sum(self.idf[t] for t in inter) / sum(self.idf[t] for t in uni)

    def _base(self, p, q):
        sh = 0
        for x, y in zip(p['path'], q['path']):
            if x != y:
                break
            sh += 1
        sh /= max(1, max(len(p['path']), len(q['path'])))
        first = 1.0 if p['t'][:1] == q['t'][:1] and p['t'] else 0.0
        return self._wjaccard(p['ts'], q['ts']) + 0.3 * sh + 0.2 * first, sh

    def _features(self, p, q, sh):
        a, b = p['ts'], q['ts']
        union = a | b
        pm, qm = p['mm'], q['mm']
        nd = min([abs(x - y) for x in p['nums'] for y in q['nums']] or [99])
        return {
            'mmc': 1.0 if (pm and qm and not (pm & qm)) else 0.0,
            'mms': 1.0 if (pm and (pm & qm)) else 0.0,
            'pc': len(p['pc'] & q['pc']) / max(1, len(p['pc'] | q['pc'])),
            'wj': self._wjaccard(a, b),
            'j': len(a & b) / len(union) if union else 0.0,
            'sh': sh,
            'same': 1.0 if p['categ'] == q['categ'] else 0.0,
            'first': 1.0 if p['t'][:1] == q['t'][:1] and p['t'] else 0.0,
            'first2': 1.0 if p['t'][:2] == q['t'][:2] else 0.0,
            'first3': 1.0 if p['t'][:3] == q['t'][:3] else 0.0,
            'spec': len(p['spec'] & q['spec']) / max(1, len(p['spec'] | q['spec'])),
            'brand': 1.0 if p['brand'] == q['brand'] and p['brand'] else 0.0,
            'nd': float(min(nd, 99)),
        }

    def similar(self, pid, k=24):
        """[(id, puntaje)] de los mas parecidos, de mayor a menor."""
        p = self.P[pid]
        cands = set(self.by_categ.get(p['categ'], ()))
        for x in p['ts']:
            cands.update(self.index.get(x, ()))
        cands.discard(pid)
        # Misma linea de negocio (departamento): un producto de otra linea solo entra si la linea no alcanza.
        in_dept = {c for c in cands if self.P[c]['dept'] == p['dept']}
        if len(in_dept) < k:
            in_dept = (in_dept | self.by_dept[p['dept']]) - {pid}
        if len(in_dept) >= k:
            cands = in_dept
        scored = []
        for qid in cands:
            q = self.P[qid]
            base, sh = self._base(p, q)
            scored.append((base, qid, sh))
        scored.sort(key=lambda r: (-r[0], r[1]))
        out = []
        for base, qid, sh in scored[:POOL]:
            f = self._features(p, self.P[qid], sh)
            score = self.b + sum(self.w[c] * f[c] for c in self.w)
            out.append((qid, score))
        out.sort(key=lambda r: (-r[1], r[0]))
        return out[:k]

    # ---------------------------------------------------------- complementos
    @staticmethod
    def _same_head(a, b):
        return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= 0.8

    def _rank_in(self, p, ids, per=3, different_head=False):
        pool = []
        for qid in ids:
            if qid == p['id']:
                continue
            q = self.P[qid]
            if different_head and self._same_head(p['head'], q['head']):
                continue
            same_brand = 1 if (q['brand'] == p['brand'] and p['brand']) else 0
            mm_ok = 0 if (p['mm'] and q['mm'] and not (p['mm'] & q['mm'])) else 1
            pool.append((-mm_ok, -same_brand, -self.pop.get(qid, 0), qid))
        pool.sort()
        return [r[3] for r in pool[:per]]

    def complement(self, pid, k=12):
        """Ids de productos que se usan junto con este, en orden de prioridad (varias categorias intercaladas)."""
        p = self.P[pid]
        name = self.name_of_categ.get(p['categ'], '')
        rules = self.comp_map.get(name)
        lists = []
        if rules:
            for rule in rules:
                if rule == MISMA:
                    lists.append(self._rank_in(p, self.by_categ.get(p['categ'], ()), per=4, different_head=True))
                else:
                    cid = self.categ_by_name.get(rule)
                    if cid is not None:
                        lists.append(self._rank_in(p, self.by_categ.get(cid, ()), per=3))
        else:
            dept = name.split('/')[0].strip() if name else ''
            ids = [i for n, c in self.categ_by_name.items() if n.split('/')[0].strip() == dept and c != p['categ']
                   for i in self.by_categ.get(c, ())]
            lists.append(self._rank_in(p, ids, per=6))
        out = []
        for rank in range(4):
            for lst in lists:
                if rank < len(lst) and lst[rank] not in out:
                    out.append(lst[rank])
        return out[:k]
