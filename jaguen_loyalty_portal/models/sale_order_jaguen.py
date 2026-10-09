# -*- coding: utf-8 -*-
"""Reglas de pedido JAGUEN (oct/2026):

1. Los regalos/vales de los 4 programas JAGUEN solo se pueden reclamar con
   puntos YA PAGADOS: nunca con los puntos del propio pedido que se esta
   armando (esos puntos no cuentan hasta que la factura este pagada).
2. En la tienda en linea (carrito y proceso de compra) no se muestra ni se
   aplica automaticamente ningun regalo/vale de los 4 programas JAGUEN.
   Reclamarlos es solo en el backend.
3. La direccion de factura es SIEMPRE la empresa (contacto comercial), nunca
   una persona. El Cliente y la direccion de entrega no se modifican.
"""
from odoo import api, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # -- 1) Solo puntos pagados -------------------------------------------
    def _get_real_points_for_coupon(self, coupon, post_confirm=False):
        points = super()._get_real_points_for_coupon(coupon, post_confirm=post_confirm)
        if (
            coupon.program_id.x_jaguen_loyalty_group
            and self.state not in ('sale', 'done')
            and coupon.program_id.applies_on != 'future'
        ):
            # Odoo suma aqui los puntos que ESTE pedido daria al
            # confirmarse; para JAGUEN no cuentan hasta que se pague la
            # factura, asi que se restan.
            own = sum(self.coupon_point_ids.filtered(
                lambda p: p.coupon_id == coupon).mapped('points'))
            points = coupon.currency_id.round(points - own)
        return points

    # -- 2) Nada de regalos JAGUEN en la tienda en linea -------------------
    def _jaguen_hide_website_rewards(self, result):
        if self.website_id:
            for coupon in list(result):
                if coupon.program_id.x_jaguen_loyalty_group:
                    del result[coupon]
        return result

    def _get_claimable_rewards(self, forced_coupons=None):
        result = super()._get_claimable_rewards(forced_coupons=forced_coupons)
        # Sin aceptar los Terminos y Condiciones no se puede reclamar nada.
        for coupon in list(result):
            if coupon.program_id.x_jaguen_loyalty_group and not coupon._jaguen_is_accepted():
                del result[coupon]
        return self._jaguen_hide_website_rewards(result)

    def _get_claimable_and_showable_rewards(self):
        result = super()._get_claimable_and_showable_rewards()
        return self._jaguen_hide_website_rewards(result)

    # -- 3) Factura siempre a la empresa -----------------------------------
    def _compute_partner_invoice_id(self):
        super()._compute_partner_invoice_id()
        for order in self:
            if order.partner_id:
                order.partner_invoice_id = order.partner_id.commercial_partner_id

    @api.model_create_multi
    def create(self, vals_list):
        Partner = self.env['res.partner']
        for vals in vals_list:
            if vals.get('partner_invoice_id'):
                vals['partner_invoice_id'] = Partner.browse(
                    vals['partner_invoice_id']).commercial_partner_id.id
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('partner_invoice_id'):
            vals = dict(vals, partner_invoice_id=self.env['res.partner'].browse(
                vals['partner_invoice_id']).commercial_partner_id.id)
        return super().write(vals)
