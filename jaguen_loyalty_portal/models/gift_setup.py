# -*- coding: utf-8 -*-
import logging

from odoo import api, models

from .gift_catalog import GIFT_CATALOG

_logger = logging.getLogger(__name__)

GIFT_PROGRAM_TAG = {'starter': 'tag_regalo_starter_%s', 'mpp': 'tag_regalo_mpp_%s'}


class JaguenGiftSetup(models.AbstractModel):
    _name = 'jaguen.gift.setup'
    _description = 'Carga de regalos de JAGUEN Starter y Mi Primer Pedido'

    @api.model
    def _find_product(self, code, name):
        """Producto real por codigo interno (o por nombre si el regalo no trae codigo)."""
        Product = self.env['product.product'].sudo()
        if code:
            return Product.search([('default_code', '=', code)], limit=1)
        return Product.search([('name', '=', name)], limit=1)

    @api.model
    def setup_gifts(self):
        """Pone cada regalo del catalogo en la etiqueta de su nivel.

        Usa los productos que ya existen en Odoo (se buscan por codigo
        interno); NUNCA crea productos. Es seguro correrlo varias veces: deja en cada etiqueta exactamente los
        productos del catalogo."""
        Product = self.env['product.product'].sudo()
        wanted = {}
        missing = []
        for program, amount, code, name, cost, provider in GIFT_CATALOG:
            tag = self.env.ref('jaguen_loyalty_portal.' + GIFT_PROGRAM_TAG[program] % amount)
            product = self._find_product(code, name)
            if not product:
                # No se crean productos: si falta uno, se salta y se avisa.
                missing.append(code or name)
                continue
            # Etiqueta a nivel de VARIANTE: asi un producto con tallas (como la
            # bota) solo ofrece la talla elegida y no todas.
            product.write({'additional_product_tag_ids': [(4, tag.id)]})
            wanted.setdefault(tag.id, set()).add(product.id)
        for tag_id, product_ids in wanted.items():
            stale = Product.with_context(active_test=False).search([
                '|', ('additional_product_tag_ids', 'in', [tag_id]), ('product_tag_ids', 'in', [tag_id]),
                ('id', 'not in', list(product_ids))])
            if stale:
                stale.write({
                    'additional_product_tag_ids': [(3, tag_id)],
                    'product_tag_ids': [(3, tag_id)],
                })
        if missing:
            _logger.warning('Regalos sin producto en Odoo (no se crearon): %s', missing)
        return missing

    @api.model
    def gift_order(self, program, amount):
        """Orden (codigo o nombre) de las opciones de un nivel, segun el catalogo."""
        return [c or n for p, a, c, n, _cost, _prov in GIFT_CATALOG if p == program and a == amount]
