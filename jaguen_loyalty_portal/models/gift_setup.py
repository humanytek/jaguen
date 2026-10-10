# -*- coding: utf-8 -*-
from odoo import api, models

from .gift_catalog import GIFT_CATALOG

GIFT_PROGRAM_TAG = {'starter': 'tag_regalo_starter_%s', 'mpp': 'tag_regalo_mpp_%s'}


class JaguenGiftSetup(models.AbstractModel):
    _name = 'jaguen.gift.setup'
    _description = 'Carga de regalos de JAGUEN Starter y Mi Primer Pedido'

    @api.model
    def _find_product(self, code, name):
        """Producto real por codigo interno. Si el regalo no trae codigo (por
        ejemplo una bota que en Odoo existe por tallas), se usa un producto
        de regalo propio, buscado por su nombre."""
        Product = self.env['product.product'].sudo()
        if code:
            return Product.search([('default_code', '=', code)], limit=1)
        return Product.search([('name', '=', self._gift_name(name))], limit=1)

    @api.model
    def _gift_name(self, name):
        return 'Regalo JAGUEN - %s' % name

    @api.model
    def setup_gifts(self):
        """Pone cada regalo del catalogo en la etiqueta de su nivel.

        Usa los productos que ya existen en Odoo (se buscan por codigo
        interno); solo crea el producto cuando no lo encuentra. Es seguro
        correrlo varias veces: deja en cada etiqueta exactamente los
        productos del catalogo."""
        Product = self.env['product.product'].sudo()
        wanted = {}
        for program, amount, code, name, cost, provider in GIFT_CATALOG:
            tag = self.env.ref('jaguen_loyalty_portal.' + GIFT_PROGRAM_TAG[program] % amount)
            product = self._find_product(code, name)
            if not product:
                product = Product.create({
                    'name': name if code else self._gift_name(name),
                    'default_code': code or False,
                    'type': 'consu',
                    'list_price': cost,
                    'standard_price': cost,
                    'sale_ok': False,
                    'purchase_ok': True,
                    'description': 'Codigo Odoo: %s | Proveedor: %s' % (code or 'pendiente', provider),
                })
            product.write({'product_tag_ids': [(4, tag.id)]})
            wanted.setdefault(tag.id, set()).add(product.product_tmpl_id.id)
        for tag_id, tmpl_ids in wanted.items():
            # La etiqueta vive en la plantilla del producto (todas sus
            # variantes la comparten), por eso se compara por plantilla.
            stale = Product.with_context(active_test=False).search([
                ('product_tag_ids', 'in', [tag_id]),
                ('product_tmpl_id', 'not in', list(tmpl_ids))])
            if stale:
                stale.write({'product_tag_ids': [(3, tag_id)]})
        return True

    @api.model
    def gift_order(self, program, amount):
        """Orden (codigo o nombre) de las opciones de un nivel, segun el catalogo."""
        return [c or n for p, a, c, n, _cost, _prov in GIFT_CATALOG if p == program and a == amount]
