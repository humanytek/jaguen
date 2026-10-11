# -*- coding: utf-8 -*-
from odoo import models


class WebsiteSnippetFilter(models.Model):
    _inherit = 'website.snippet.filter'

    def _get_products_alternative_products(self, website, limit, domain, product_template_id=None, **kwargs):
        """Muestra los alternativos en el orden guardado en jaguen.alternative.rank
        (Odoo los reordena por nombre). Los que no tienen posicion van al final."""
        products = super()._get_products_alternative_products(
            website, limit, domain, product_template_id=product_template_id, **kwargs)
        if products and product_template_id:
            ranks = self.env['jaguen.alternative.rank'].sudo().search_read(
                [('template_id', '=', int(product_template_id))], ['alternative_id', 'sequence'])
            position = {r['alternative_id'][0]: r['sequence'] for r in ranks}
            if position:
                products = products.sorted(
                    key=lambda p: (position.get(p.product_tmpl_id.id, 9999), p.product_tmpl_id.name or '', p.id))
        return products
