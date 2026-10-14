from odoo import models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _jaguen_show_alternatives(self):
        """True si la ficha debe mostrar el carrusel de alternativos aunque el producto no tenga manuales."""
        self.ensure_one()
        return self.env['ir.config_parameter'].sudo().get_param('jaguen_cart_accessories.alt_auto', '1') != '0'
