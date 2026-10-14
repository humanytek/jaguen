# -*- coding: utf-8 -*-
import json
import logging
import os
import random
import time
from datetime import timedelta

from odoo import api, fields, models

from . import alt_engine

_logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
PARAM_AUTO = 'jaguen_cart_accessories.alt_auto'              # '0' apaga los alternativos automaticos
PARAM_DAYS = 'jaguen_cart_accessories.alt_rotation_days'     # cada cuantos dias cambia la seleccion (1 = diario)
PARAM_OFFSET = 'jaguen_cart_accessories.alt_day_offset'      # entero: adelanta/atrasa el dia para forzar otra seleccion
TOTAL = 8        # alternativos que se muestran (el carrusel enseña 4 a la vez)
NEAR = 3         # los primeros: casi identicos (otros colores / medidas del mismo modelo)
NEAR_MIN = -2.0  # puntaje minimo para contar como "casi identico"; si no hay, esos espacios se llenan con complementos
REFRESH_DAYS = 7  # cada cuanto se vuelven a calcular los candidatos de un producto


def _load_json(name):
    with open(os.path.join(DATA_DIR, name), encoding='utf-8') as handle:
        return json.load(handle)


class JaguenAltCache(models.Model):
    """Candidatos de alternativos de cada producto (los calcula alt_engine; la tienda arma cada dia 8 con ellos).

    Guarda los mas parecidos y los complementos, no la lista final: asi la seleccion puede rotar sin reescribir
    el campo "Productos alternativos" de los productos."""
    _name = 'jaguen.alt.cache'
    _description = 'Candidatos de productos alternativos (JAGUEN)'

    template_id = fields.Many2one('product.template', string='Producto', required=True, ondelete='cascade', index=True)
    similar = fields.Text(string='Parecidos (JSON)')
    complement = fields.Text(string='Complementos (JSON)')
    computed_on = fields.Datetime(string='Calculado', default=fields.Datetime.now)

    _sql_constraints = [
        ('template_uniq', 'unique(template_id)', 'Ese producto ya tiene sus candidatos calculados.'),
    ]

    # ------------------------------------------------------------------ calculo
    @api.model
    def _universe_domain(self):
        return [('is_published', '=', True), ('sale_ok', '=', True), ('active', '=', True)]

    @api.model
    def _build_engine(self):
        templates = self.env['product.template'].sudo().search(self._universe_domain())
        products = [{
            'id': t.id, 'name': t.name or '', 'categ_id': t.categ_id.id,
            'categ_name': t.categ_id.display_name or '', 'public_categ_ids': t.public_categ_ids.ids,
        } for t in templates]
        popularity = {}
        rows = self.env['sale.order.line'].sudo()._read_group(
            [('order_id.state', 'in', ('sale', 'done')), ('product_id', '!=', False)],
            ['product_id'], ['product_uom_qty:sum'])
        for product, qty in rows:
            tid = product.product_tmpl_id.id
            popularity[tid] = popularity.get(tid, 0) + (qty or 0)
        return alt_engine.Engine(products, _load_json('weights.json'), _load_json('complement_map.json'), popularity)

    @api.model
    def _cron_rebuild(self, limit=6000, budget=100):
        """Calcula los candidatos de los productos que no los tienen (nuevos) y vuelve a calcular los de mas de
        REFRESH_DAYS dias. Se detiene al llegar al tiempo maximo y sigue en la siguiente corrida."""
        started = time.time()
        engine = self._build_engine()
        existing = {rec.template_id.id: rec for rec in self.sudo().search([])}
        # Los que ya no estan publicados no hacen falta
        gone = [rec.id for tid, rec in existing.items() if tid not in engine.P]
        if gone:
            self.sudo().browse(gone).unlink()
        limit_date = fields.Datetime.now() - timedelta(days=REFRESH_DAYS)
        missing = [tid for tid in engine.P if tid not in existing]
        old = sorted((rec for tid, rec in existing.items() if tid in engine.P and (rec.computed_on or limit_date) <= limit_date),
                     key=lambda rec: rec.computed_on or limit_date)
        todo = (missing + [rec.template_id.id for rec in old])[:limit]
        done = 0
        for tid in todo:
            if time.time() - started > budget:
                break
            vals = {
                'similar': json.dumps([[sid, round(score, 3)] for sid, score in engine.similar(tid, 24)]),
                'complement': json.dumps(engine.complement(tid, 12)),
                'computed_on': fields.Datetime.now(),
            }
            rec = existing.get(tid)
            if rec:
                rec.sudo().write(vals)
            else:
                self.sudo().create(dict(vals, template_id=tid))
            done += 1
        _logger.info('Alternativos JAGUEN: %s productos calculados, %s pendientes, %.1f s',
                     done, max(0, len(todo) - done), time.time() - started)
        return done

    # ------------------------------------------------------------ seleccion diaria
    @api.model
    def jaguen_pick(self, template_id, limit=TOTAL):
        """Ids de producto (plantilla) que se muestran hoy como alternativos de `template_id`:
        3 casi identicos + 1 complemento + el resto de la misma linea; cambia cada dia. Lista vacia si no hay candidatos."""
        rec = self.sudo().search([('template_id', '=', template_id)], limit=1)
        if not rec:
            return []
        scores = {sid: score for sid, score in json.loads(rec.similar or '[]')}
        similar = list(scores)
        complement = json.loads(rec.complement or '[]')
        wanted = list(set(similar + complement))
        if not wanted:
            return []
        alive = set(self.env['product.template'].sudo().search(
            self._universe_domain() + [('id', 'in', wanted)]).ids)
        similar = [i for i in similar if i in alive and i != template_id]
        complement = [i for i in complement if i in alive and i != template_id]
        params = self.env['ir.config_parameter'].sudo()
        try:
            days = max(1, int(params.get_param(PARAM_DAYS) or 1))
            offset = int(params.get_param(PARAM_OFFSET) or 0)
        except ValueError:
            days, offset = 1, 0
        rng = random.Random('%s-%s' % (template_id, (fields.Date.context_today(self).toordinal() + offset) // days))
        picked = []
        near_pool = [i for i in similar[:NEAR * 2] if scores.get(i, -9) >= NEAR_MIN]
        picked += sorted(rng.sample(near_pool, min(NEAR, len(near_pool))), key=similar.index)
        # el complemento (y, si no hubo casi identicos suficientes, los espacios que faltaron)
        comp_pool = [i for i in complement if i not in picked][:6 + NEAR]
        want = 1 + (NEAR - len(picked))
        picked += rng.sample(comp_pool, min(want, len(comp_pool)))
        rest = [i for i in similar if i not in picked]
        line_pool = rest[:16]
        picked += sorted(rng.sample(line_pool, min(max(0, limit - len(picked)), len(line_pool))),
                         key=similar.index)
        # relleno: primero el resto de los parecidos, luego los demas complementos
        for i in rest + [c for c in complement if c not in picked]:
            if len(picked) >= limit:
                break
            if i not in picked:
                picked.append(i)
        picked = picked[:limit]
        return self._slots_6_7(template_id, picked, similar + complement, rng)

    @api.model
    def _slots_6_7(self, template_id, picked, pool, rng):
        """Lugares 6 y 7: por prioridad misma marca, mismo proveedor, misma categoria; nunca productos que ya salen
        en los lugares 1 a 4. Si ninguno califica, quedan como estaban."""
        if len(picked) < 7:
            return picked
        out = list(picked)
        cands = []
        for i in out[5:] + pool:
            if i != template_id and i not in out[:5] and i not in cands:
                cands.append(i)
        ids = list(set([template_id] + cands))
        tmpls = {t.id: t for t in self.env['product.template'].sudo().browse(ids)}
        sup = {}
        for line in self.env['product.supplierinfo'].sudo().search(
                ['|', ('product_tmpl_id', 'in', ids), ('product_id.product_tmpl_id', 'in', ids)]):
            tid = line.product_tmpl_id.id or line.product_id.product_tmpl_id.id
            sup.setdefault(tid, set()).add(line.partner_id.id)

        def brand(t):
            toks = alt_engine.tokens(t.name or '')
            return toks[-1] if toks else ''

        me = tmpls.get(template_id)
        if not me:
            return picked
        mybrand, mysup = brand(me), sup.get(template_id) or set()

        def tier(i):
            t = tmpls.get(i)
            if not t:
                return 9
            if mybrand and brand(t) == mybrand:
                return 1
            if mysup and (sup.get(i) or set()) & mysup:
                return 2
            if t.categ_id == me.categ_id:
                return 3
            return 9

        rng.shuffle(cands)
        best = sorted((i for i in cands if tier(i) < 9), key=tier)[:2]
        for slot, new in zip((5, 6), best):
            if new in out:  # ya estaba en otro lugar (el 6, 7 u 8): intercambio
                other = out.index(new)
                out[other] = out[slot]
            out[slot] = new
        return out
