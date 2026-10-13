# -*- coding: utf-8 -*-
from odoo import api, fields, models

PERSONAL_MIN_PARAM = 'jaguen_website.personal_min_amount'
PERSONAL_MIN_DEFAULT = 4000.0
CART_MIN_PARAM = 'jaguen_website.cart_min_amount'
CART_MIN_DEFAULT = 1000.0


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    x_jaguen_personal_min = fields.Float(compute='_compute_jaguen_personal_min')
    x_jaguen_personal_min_gap = fields.Float(compute='_compute_jaguen_personal_min')
    x_jaguen_min_reason = fields.Char(compute='_compute_jaguen_personal_min')

    def _jaguen_is_guest_cart(self):
        """True si el carrito es de alguien que no inicio sesion (visitante que compra sin registrarse)."""
        self.ensure_one()
        partner = self.partner_id.sudo()
        public_partner = self.website_id.sudo().user_id.partner_id
        return not partner or partner == public_partner or not partner.user_ids

    @api.depends('partner_id', 'website_id', 'state', 'order_line.price_subtotal', 'order_line.is_delivery',
                 'order_line.is_reward_line', 'order_line.display_type')
    def _compute_jaguen_personal_min(self):
        """Pedido minimo en el carrito del sitio (antes de IVA, sin envio ni descuentos de cupon):
        - $4,000 para visitantes que compran sin registrarse (sin iniciar sesion) y para clientes registrados como
          "compra personal";
        - $1,000 para todos los demas (empresas y personas fisicas con actividad empresarial registradas).
        Las cotizaciones hechas por un vendedor (sin sitio web) no tienen minimo.
        """
        get = self.env['ir.config_parameter'].sudo().get_param

        def _amount(key, default):
            try:
                return float(get(key)) if get(key) else default
            except ValueError:
                return default
        personal_min = _amount(PERSONAL_MIN_PARAM, PERSONAL_MIN_DEFAULT)
        cart_min = _amount(CART_MIN_PARAM, CART_MIN_DEFAULT)
        for order in self:
            minimum = cart_min
            gap = 0.0
            reason = False
            if order.website_id and order.state == 'draft' and order.order_line.filtered(lambda l: not l.display_type):
                if order._jaguen_is_guest_cart():
                    reason, minimum = 'guest', personal_min
                elif order.partner_id.commercial_partner_id.sudo().jaguen_personal:
                    reason, minimum = 'personal', personal_min
                else:
                    reason = 'general'
                lines = order.order_line.filtered(
                    lambda l: not l.display_type and not l.is_delivery and not l.is_reward_line)
                gap = max(0.0, minimum - sum(lines.mapped('price_subtotal')))
            order.x_jaguen_personal_min = minimum
            order.x_jaguen_personal_min_gap = round(gap, 2)
            order.x_jaguen_min_reason = reason if gap > 0 else False
