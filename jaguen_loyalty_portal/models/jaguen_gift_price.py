# -*- coding: utf-8 -*-
"""Precio simbolico de los regalos de JAGUEN Starter y Mi Primer Pedido.

Un concepto de CFDI de ingreso no puede tener valor unitario ni base de IVA en cero, y Odoo arma el regalo
como el producto a precio de lista con 100% de descuento (base en cero). Por eso el regalo entra al pedido
a un precio simbolico (parametro 'jaguen_loyalty_portal.regalo_precio', hoy $0.01 mas IVA) y sin descuento.
Solo aplica a la linea de premio de esos dos programas: el precio de lista y la venta normal del mismo
producto no cambian."""
from odoo import api, models

GRUPOS_REGALO = ('onboarding', 'pedido_monto')
PARAM_PRECIO = 'jaguen_loyalty_portal.regalo_precio'


def _precio_regalo(env):
    try:
        return float(env['ir.config_parameter'].sudo().get_param(PARAM_PRECIO, '0.01'))
    except (TypeError, ValueError):
        return 0.01


class SaleOrderJaguenGiftPrice(models.Model):
    _inherit = 'sale.order'

    def _get_reward_values_product(self, reward, coupon, product=None, **kwargs):
        values = super()._get_reward_values_product(reward, coupon, product=product, **kwargs)
        if reward.program_id.x_jaguen_loyalty_group in GRUPOS_REGALO:
            precio = _precio_regalo(self.env)
            for vals in values:
                vals['price_unit'] = precio
                vals['discount'] = 0.0
        return values


class SaleOrderLineJaguenGiftPrice(models.Model):
    _inherit = 'sale.order.line'

    def _jaguen_es_regalo(self):
        self.ensure_one()
        return bool(
            self.reward_id and self.reward_id.reward_type == 'product'
            and self.reward_id.program_id.x_jaguen_loyalty_group in GRUPOS_REGALO)

    def _compute_price_unit(self):
        super()._compute_price_unit()
        regalos = self.filtered(lambda l: l.reward_id and l._jaguen_es_regalo())
        if regalos:
            precio = _precio_regalo(self.env)
            for line in regalos:
                line.price_unit = precio

    def _compute_discount(self):
        super()._compute_discount()
        for line in self.filtered(lambda l: l.reward_id and l._jaguen_es_regalo()):
            line.discount = 0.0
