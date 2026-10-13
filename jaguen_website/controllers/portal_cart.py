# -*- coding: utf-8 -*-
import logging

from odoo import http
from odoo.exceptions import AccessError, MissingError
from odoo.http import request
from odoo.addons.sale.controllers.portal import CustomerPortal

_logger = logging.getLogger(__name__)


class CustomerPortalBackToCart(CustomerPortal):

    @http.route('/my/orders/<int:order_id>/back_to_cart', type='http', auth='public', methods=['POST'], website=True)
    def jaguen_back_to_cart(self, order_id, access_token=None, **kw):
        """"Regresar al carrito": el cliente corrige una cotizacion que salio de su carrito (aun sin firmar ni pagar).

        Sus productos pasan a su carrito actual y esta cotizacion se cancela; al terminar la compra se genera una
        cotizacion nueva (con folio nuevo)."""
        try:
            order_sudo = self._document_check_access('sale.order', order_id, access_token=access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
        if not (order_sudo.website_id and order_sudo.state == 'sent' and not order_sudo.signature):
            return request.redirect(order_sudo.get_portal_url())
        try:
            with request.env.cr.savepoint():
                cart = request.website.sale_get_order(force_create=True)
                for line in order_sudo.order_line.filtered(
                        lambda l: not l.display_type and not l.is_delivery and not l.is_reward_line and l.product_id):
                    cart._cart_update(product_id=line.product_id.id, add_qty=line.product_uom_qty)
                # Sin avisos ni notas para nadie: una cotizacion que cambia no le importa al equipo, solo las ordenes de venta.
                # disable_cancel_warning: sin esto, Odoo no cancela la cotizacion enviada y solo devuelve su ventana de confirmacion
                order_sudo.with_context(disable_cancel_warning=True, tracking_disable=True, mail_notrack=True,
                                        mail_auto_subscribe_no_notify=True).action_cancel()
                if order_sudo.state != 'cancel':
                    raise ValueError('La cotizacion no se cancelo')
        except Exception:
            _logger.exception('No se pudo regresar al carrito la cotizacion %s', order_id)
            return request.redirect(order_sudo.get_portal_url())
        return request.redirect('/shop/cart')
