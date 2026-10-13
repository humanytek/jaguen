# -*- coding: utf-8 -*-
from odoo import api, fields, models

PERSONAL_MIN_PARAM = 'jaguen_website.personal_min_amount'
PERSONAL_MIN_DEFAULT = 4000.0


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    x_jaguen_personal_min = fields.Float(compute='_compute_jaguen_personal_min')
    x_jaguen_personal_min_gap = fields.Float(compute='_compute_jaguen_personal_min')

    @api.depends('partner_id', 'website_id', 'state', 'order_line.price_subtotal', 'order_line.is_delivery',
                 'order_line.is_reward_line', 'order_line.display_type')
    def _compute_jaguen_personal_min(self):
        """Compra personal desde el sitio: pedido minimo de $4,000 antes de IVA (sin envio ni descuentos de cupon).

        Solo aplica a pedidos del carrito de clientes registrados como "compra personal". Empresas y personas
        fisicas con actividad empresarial no tienen minimo; las cotizaciones hechas por un vendedor tampoco.
        """
        param = self.env['ir.config_parameter'].sudo().get_param(PERSONAL_MIN_PARAM)
        try:
            minimum = float(param) if param else PERSONAL_MIN_DEFAULT
        except ValueError:
            minimum = PERSONAL_MIN_DEFAULT
        for order in self:
            order.x_jaguen_personal_min = minimum
            gap = 0.0
            partner = order.partner_id.commercial_partner_id
            if order.website_id and order.state == 'draft' and partner and partner.jaguen_personal:
                lines = order.order_line.filtered(
                    lambda l: not l.display_type and not l.is_delivery and not l.is_reward_line)
                subtotal = sum(lines.mapped('price_subtotal'))
                gap = max(0.0, minimum - subtotal)
            order.x_jaguen_personal_min_gap = round(gap, 2)
