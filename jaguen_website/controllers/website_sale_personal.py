# -*- coding: utf-8 -*-
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale


class WebsiteSalePersonal(WebsiteSale):
    """Compra personal: si el pedido no llega al minimo no se puede pasar del carrito (direccion, envio, pago)."""

    def _check_cart(self, order_sudo):
        redirection = super()._check_cart(order_sudo)
        if redirection:
            return redirection
        if order_sudo and order_sudo.x_jaguen_personal_min_gap > 0 and request.httprequest.path != '/shop/cart':
            return request.redirect('/shop/cart')
