from odoo import _, fields, http
from markupsafe import Markup
from odoo.exceptions import ValidationError
from odoo.http import request
from odoo.addons.website_sale.controllers.payment import PaymentPortal


class PaymentPortalJaguen(PaymentPortal):
    """Con PayPal el cliente debe decir si paga con tarjeta de credito o debito.

    Se guarda en el pedido como forma de pago del CFDI: 04 (credito) o 28 (debito).
    """

    @http.route()
    def shop_payment_transaction(self, order_id, access_token, **kwargs):
        card_type = kwargs.pop('jaguen_card_type', None)
        accepted = kwargs.pop('jaguen_tyc', None) in ('1', 'true', 'True', True, 1)
        if not accepted:
            raise ValidationError(_(
                "Debes aceptar los términos y condiciones para poder pagar."))
        provider = request.env['payment.provider'].sudo().browse(
            int(kwargs.get('provider_id') or 0)).exists()
        is_paypal = bool(provider) and provider.code == 'paypal'
        if is_paypal and card_type not in ('credit', 'debit'):
            raise ValidationError(_(
                "Debes elegir el tipo de Tarjeta que usarás"))
        result = super().shop_payment_transaction(order_id, access_token, **kwargs)
        self._jaguen_register_tyc(order_id)
        if is_paypal:
            tx = request.env['payment.transaction'].sudo().search(
                [('reference', '=', result.get('reference'))], limit=1)
            if tx:
                tx.jaguen_cart_card_type = card_type
                method = tx._jaguen_card_method()
                order = request.env['sale.order'].sudo().browse(order_id).exists()
                if method and order:
                    order.l10n_mx_edi_payment_method_id = method
        return result

    def _jaguen_register_tyc(self, order_id):
        """Guarda cuando y desde que IP se aceptaron los T&C (pedido y cliente)."""
        order = request.env['sale.order'].sudo().browse(order_id).exists()
        if not order:
            return
        now = fields.Datetime.now()
        ip = request.httprequest.remote_addr
        order.write({'jaguen_tyc_date': now, 'jaguen_tyc_ip': ip})
        order.partner_id.write({'jaguen_tyc_date': now})
        order.message_post(body=Markup(
            "El cliente aceptó los términos y condiciones y el aviso de privacidad al pagar (IP %s)."
        ) % ip, message_type='comment', subtype_xmlid='mail.mt_note')
