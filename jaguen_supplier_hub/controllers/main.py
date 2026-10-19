from odoo.http import request

from odoo.addons.website_sale.controllers.main import WebsiteSale


class WebsiteSaleApihub(WebsiteSale):

    def _check_cart(self, order_sudo):
        """Verificación en vivo al confirmar el pedido y al entrar al pago (docs 7e): si ya no hay lo que el cliente pidió,
        regresa al carrito con el aviso. Con el modo 'solo observar' únicamente registra."""
        redirection = super()._check_cart(order_sudo)
        if redirection or not order_sudo:
            return redirection
        if request.httprequest.path in ("/shop/confirm_order", "/shop/payment"):
            problems = request.env["apihub.live"].sudo().order_check(order_sudo, "confirmar")
            if problems:
                for line, message in problems:
                    line.shop_warning = message
                order_sudo.shop_warning = request.env._("Algunos productos de tu carrito ya no están disponibles en la cantidad pedida.")
                return request.redirect("/shop/cart")
        return redirection
