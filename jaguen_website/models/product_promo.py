# -*- coding: utf-8 -*-
from odoo import api, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    @api.model
    def jaguen_promo_cards(self, term):
        """Datos para las tarjetas de la pagina /promociones: productos publicados cuyo nombre contiene `term`.

        Devuelve nombre, liga a su ficha, descripcion de ecommerce y el precio igual que lo ve el visitante en la tienda
        (lista de precios del sitio, con IVA). Solo expone lo que ya es publico en la tienda.
        """
        website = self.env['website'].get_current_website()
        cards = []
        products = self.sudo().search(
            [('name', 'ilike', term), ('is_published', '=', True), ('sale_ok', '=', True)], order='name')
        for product in products:
            info = product._get_combination_info(only_template=True)
            cards.append({
                'id': product.id,
                'name': product.name,
                'url': product.website_url,
                'description': product.description_ecommerce or '',
                'price': info.get('price'),
                'currency': website.currency_id,
            })
        return cards
