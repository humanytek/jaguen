from odoo.http import request, route

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

    @route("/shop/apihub/offer/<int:offer_id>/<string:action>", type="http", auth="public", website=True, methods=["POST"], sitemap=False)
    def apihub_offer(self, offer_id, action, **_kwargs):
        """Respuesta del cliente a la oferta de piezas sobre pedido: 'accept' (Aceptar) o 'decline' (No, gracias)."""
        order = request.website.sale_get_order()
        offer = request.env["apihub.cart.offer"].sudo().browse(offer_id).exists()
        if order and offer and offer.order_id.id == order.id:
            if action == "accept":
                offer.action_accept()
            elif action == "decline":
                offer.action_decline()
            elif action == "remove":
                offer.action_remove()
        return request.redirect("/shop/cart")
