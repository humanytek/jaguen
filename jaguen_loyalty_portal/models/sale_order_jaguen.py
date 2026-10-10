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
from odoo import _, api, models
from odoo.exceptions import UserError, ValidationError


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

    # -- 1b) Un regalo por canje -------------------------------------------
    def _get_reward_values_product(self, reward, coupon, product=None, **kwargs):
        """Odoo entrega tantas unidades del regalo como alcancen los puntos
        (puntos / puntos del premio, redondeado hacia abajo): con 30,000
        puntos y un premio de 10,000 pondria 3 regalos y gastaria los 30,000.
        En Starter y Mi Primer Pedido cada canje es UN regalo y solo cuesta
        los puntos de ese nivel (el cliente puede conservar el resto)."""
        values = super()._get_reward_values_product(reward, coupon, product=product, **kwargs)
        group = reward.program_id.x_jaguen_loyalty_group
        if group in ('onboarding', 'pedido_monto'):
            if group == 'onboarding':
                etiqueta = '[Regalo JAGUEN Starter]'
            else:
                monto = (reward.program_id.name or '').split(' de ', 1)[-1].rstrip('+').strip()
                etiqueta = '[Regalo Mi Primer Pedido de %s]' % monto
            for vals in values:
                vals['product_uom_qty'] = reward.reward_product_qty or 1
                vals['points_cost'] = reward.required_points
                # Solo la DESCRIPCION de la linea lleva la etiqueta del regalo;
                # el nombre del producto no se toca.
                prod = self.env['product.product'].browse(vals.get('product_id'))
                if prod:
                    # Nombre con codigo, sin la descripcion de venta (el carrito de la
                    # tienda ya imprime esa descripcion debajo y salia repetida).
                    vals['name'] = '%s - %s' % (etiqueta, prod.with_context(
                        lang=self.partner_id.lang).display_name)
        return values

    # -- 2) Nada de regalos JAGUEN en la tienda en linea -------------------
    def _jaguen_hide_website_rewards(self, result, keep_chosen=False):
        """En la tienda no se ofrece ningun regalo/vale JAGUEN, salvo el que
        el cliente escoge con el boton de su portal (contexto
        jaguen_portal_gift) o que ya esta en su carrito (keep_chosen)."""
        if self.website_id and not self.env.context.get('jaguen_portal_gift'):
            chosen = self.order_line.filtered(lambda l: l.reward_id).mapped('coupon_id') if keep_chosen else self.env['loyalty.card']
            for coupon in list(result):
                if coupon.program_id.x_jaguen_loyalty_group and coupon not in chosen:
                    del result[coupon]
        return result

    def _get_claimable_rewards(self, forced_coupons=None):
        result = super()._get_claimable_rewards(forced_coupons=forced_coupons)
        # Sin aceptar los Terminos y Condiciones no se puede reclamar nada.
        for coupon in list(result):
            if coupon.program_id.x_jaguen_loyalty_group and not coupon._jaguen_is_accepted():
                del result[coupon]
        return self._jaguen_hide_website_rewards(result, keep_chosen=True)

    def _get_claimable_and_showable_rewards(self):
        result = super()._get_claimable_and_showable_rewards()
        return self._jaguen_hide_website_rewards(result)

    # -- 2b) Un carrito con solo el regalo ($0) no se puede pagar ----------
    def _jaguen_gift_only(self):
        """True si el pedido solo trae regalos de recompensa (nada con costo)."""
        self.ensure_one()
        lines = self.order_line.filtered(lambda l: not l.display_type)
        # El cargo de envio no cuenta como compra: solo productos reales.
        paid = lines.filtered(lambda l: not l.is_reward_line and not ('is_delivery' in l._fields and l.is_delivery) and l.price_subtotal > 0)
        return bool(lines.filtered('is_reward_line')) and not paid

    def jaguen_is_gift_only(self):
        """Version publica (para el aviso del carrito)."""
        self.ensure_one()
        return self._jaguen_gift_only()

    def _check_cart_is_ready_to_be_paid(self):
        if self.website_id and self._jaguen_gift_only():
            raise ValidationError(_(
                'Tu regalo se entrega junto con una compra: agrega al menos un '
                'producto a tu carrito para poder hacer tu pedido.'))
        return super()._check_cart_is_ready_to_be_paid()

    def action_confirm(self):
        for order in self.filtered('website_id'):
            if order._jaguen_gift_only():
                raise UserError(_(
                    'Un pedido de la tienda no puede ser solo el regalo: debe incluir al menos un producto con costo.'))
        return super().action_confirm()

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


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def write(self, vals):
        """El regalo de Starter / Mi Primer Pedido es UNA pieza por canje: ni el
        cliente ni un vendedor pueden subirle la cantidad (saldrian 2 regalos
        gratis por un solo vale o por los puntos de un nivel)."""
        if 'product_uom_qty' in vals:
            for line in self.filtered(lambda l: l.is_reward_line and l.reward_id.program_id.x_jaguen_loyalty_group in ('onboarding', 'pedido_monto')):
                if vals['product_uom_qty'] != (line.reward_id.reward_product_qty or 1):
                    raise UserError(_('El regalo de este programa es de una sola pieza por canje; no se puede cambiar su cantidad.'))
        return super().write(vals)
