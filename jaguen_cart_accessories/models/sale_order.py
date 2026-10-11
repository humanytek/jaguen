# -*- coding: utf-8 -*-
import random
from collections import Counter

from odoo import fields, models

# --- Reglas del negocio (ver __manifest__.py) ---------------------------------
ANCHOR_CODES = ('000374', '000088', '005072')   # en orden de prioridad (referencia interna)
TOTAL = 6                                       # accesorios que se ofrecen siempre
EXPLORE = 2                                     # de lineas distintas a las del carrito
MIN_PRICE = 1.0                                 # no se ofrecen productos de $1 o menos
WEEK_OFFSET_PARAM = 'jaguen_cart_accessories.week_offset'


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # ---------------------------------------------------------------- utilidades
    def _jaguen_acc_rng(self):
        """Generador aleatorio estable durante la semana ISO para este carrito."""
        iso = fields.Date.context_today(self).isocalendar()
        try:
            offset = int(self.env['ir.config_parameter'].sudo().get_param(WEEK_OFFSET_PARAM, 0) or 0)
        except ValueError:
            offset = 0
        return random.Random('%s-%s-%s' % (iso[0], iso[1] + offset, self.id))

    def _jaguen_acc_domain(self):
        return [
            ('website_published', '=', True),
            ('sale_ok', '=', True),
            ('active', '=', True),
        ] + (self.website_id or self.env['website'].get_current_website()).website_domain()

    @staticmethod
    def _jaguen_top_ids(categories):
        """Ids de la categoria principal (linea) de cada categoria de eCommerce."""
        return {int(c.parent_path.split('/')[0]) for c in categories if c.parent_path}

    # ------------------------------------------------------------------ principal
    def _cart_accessories(self):
        """Accesorios sugeridos del carrito (reemplaza el calculo de Odoo)."""
        self.ensure_one()
        Product = self.env['product.product']
        in_cart = self.website_order_line.product_id
        if not in_cart:
            return Product

        Template = self.env['product.template'].sudo()
        rng = self._jaguen_acc_rng()
        domain = self._jaguen_acc_domain()
        excluded = set(in_cart.ids)
        chosen = []

        def usable(product):
            """Un producto se puede ofrecer si no esta ya elegido/en el carrito y se puede vender."""
            if product.id in excluded or not product.active:
                return False
            tmpl = product.product_tmpl_id
            if not (tmpl.website_published and tmpl.sale_ok):
                return False
            if not product._website_show_quick_add():
                return False
            return (product._get_contextual_price() or 0.0) > MIN_PRICE

        def add(product):
            chosen.append(product.id)
            excluded.add(product.id)

        def take_from_templates(template_ids, n):
            """Toma hasta n productos al azar (estable en la semana) de una lista de plantillas."""
            ids = sorted(template_ids)
            rng.shuffle(ids)
            taken = 0
            for tid in ids:
                if taken >= n or len(chosen) >= TOTAL:
                    break
                tmpl = Template.browse(tid)
                if tmpl.product_variant_count != 1:   # los que piden elegir atributos no se ofrecen
                    continue
                product = Product.browse(tmpl.product_variant_id.id)
                if product and usable(product):
                    add(product)
                    taken += 1
            return taken

        # Categorias (eCommerce) y lineas de lo que ya hay en el carrito.
        cart_cats = in_cart.product_tmpl_id.public_categ_ids
        cart_tops = self._jaguen_top_ids(cart_cats)

        # 1) Ancla: el primer codigo de la lista que se pueda ofrecer.
        anchors = {t.default_code: t for t in Template.search(domain + [('default_code', 'in', ANCHOR_CODES)])}
        for code in ANCHOR_CODES:
            tmpl = anchors.get(code)
            if tmpl and tmpl.product_variant_count == 1:
                product = Product.browse(tmpl.product_variant_id.id)
                if product and usable(product):
                    add(product)
                    break

        # 2) Exploracion: dos productos de dos lineas distintas, ajenas al carrito.
        tops = self.env['product.public.category'].sudo().search([('parent_id', '=', False)]).ids
        new_tops = [t for t in tops if t not in cart_tops]
        old_tops = [t for t in tops if t in cart_tops]
        rng.shuffle(new_tops)
        rng.shuffle(old_tops)
        explored = 0
        for top in new_tops + old_tops:   # las lineas del carrito solo si no alcanzan las demas
            if explored >= EXPLORE:
                break
            ids = Template.search(domain + [('public_categ_ids', 'child_of', top)]).ids
            explored += take_from_templates(ids, 1)

        # 3) El resto: historial del cliente y, si faltan, al azar de las categorias del carrito.
        if len(chosen) < TOTAL and not self.env.user._is_public():
            partner = self.partner_id.commercial_partner_id
            lines = self.env['sale.order.line'].sudo().search([
                ('order_id.partner_id', 'child_of', partner.id),
                ('order_id.state', 'in', ('sale', 'done')),
                ('product_id', '!=', False),
            ])
            freq = Counter(pid for _oid, pid in {(l.order_id.id, l.product_id.id) for l in lines})
            ranked = sorted(freq, key=lambda pid: (-freq[pid], rng.random()))
            for pid in ranked:
                if len(chosen) >= TOTAL:
                    break
                product = Product.browse(pid)
                if usable(product):
                    add(product)

        for pool_domain in (
            [('public_categ_ids', 'in', cart_cats.ids)] if cart_cats else None,
            [('public_categ_ids', 'child_of', list(cart_tops))] if cart_tops else None,
            [],
        ):
            if len(chosen) >= TOTAL:
                break
            if pool_domain is None:
                continue
            take_from_templates(Template.search(domain + pool_domain).ids, TOTAL - len(chosen))

        return Product.browse(chosen)
