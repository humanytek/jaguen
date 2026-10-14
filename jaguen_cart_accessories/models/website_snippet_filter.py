# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class WebsiteSnippetFilter(models.Model):
    _inherit = 'website.snippet.filter'

    def _get_products_alternative_products(self, website, limit, domain, product_template_id=None, **kwargs):
        """Alternativos en la ficha del producto.

        Con los alternativos automaticos prendidos (por defecto) se muestran 8 que rotan cada dia:
        3 casi identicos, 1 complemento y 4 de la misma linea (ver alt_cache.py). Si el producto aun no tiene
        candidatos calculados, o algo falla, se muestran los de siempre en el orden guardado en
        jaguen.alternative.rank (Odoo los reordena por nombre)."""
        products = super()._get_products_alternative_products(
            website, limit, domain, product_template_id=product_template_id, **kwargs)
        if not product_template_id:
            return products
        try:
            auto = self.env['ir.config_parameter'].sudo().get_param('jaguen_cart_accessories.alt_auto', '1')
            if auto not in ('0', 'false', 'False'):
                ids = self.env['jaguen.alt.cache'].jaguen_pick(int(product_template_id), min(limit or 8, 8))
                if ids:
                    if products._name == 'product.template':
                        return products.browse(ids)
                    first = {}
                    for variant in products.env['product.product'].search([('product_tmpl_id', 'in', ids)]):
                        first.setdefault(variant.product_tmpl_id.id, variant.id)
                    variant_ids = [first[i] for i in ids if i in first]
                    if variant_ids:
                        return products.browse(variant_ids)
        except Exception:  # la tienda nunca debe fallar por esto
            _logger.exception('Alternativos automaticos: se usan los de siempre (producto %s)', product_template_id)
        if products:
            ranks = self.env['jaguen.alternative.rank'].sudo().search_read(
                [('template_id', '=', int(product_template_id))], ['alternative_id', 'sequence'])
            position = {r['alternative_id'][0]: r['sequence'] for r in ranks}
            if position:
                products = products.sorted(
                    key=lambda p: (position.get(p.product_tmpl_id.id, 9999), p.product_tmpl_id.name or '', p.id))
        return products
