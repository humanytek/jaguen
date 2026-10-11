from odoo import _, http
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
        provider = request.env['payment.provider'].sudo().browse(
            int(kwargs.get('provider_id') or 0)).exists()
        is_paypal = bool(provider) and provider.code == 'paypal'
        if is_paypal and card_type not in ('credit', 'debit'):
            raise ValidationError(_(
                "Selecciona si pagarás con tarjeta de crédito o con tarjeta de débito."))
        result = super().shop_payment_transaction(order_id, access_token, **kwargs)
        if is_paypal:
            method = request.env['l10n_mx_edi.payment.method'].sudo().search(
                [('code', '=', '04' if card_type == 'credit' else '28')], limit=1)
            order = request.env['sale.order'].sudo().browse(order_id).exists()
            if method and order:
                order.l10n_mx_edi_payment_method_id = method
        return result
