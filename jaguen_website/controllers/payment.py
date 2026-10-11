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
            tx = request.env['payment.transaction'].sudo().search(
                [('reference', '=', result.get('reference'))], limit=1)
            if tx:
                tx.jaguen_cart_card_type = card_type
                method = tx._jaguen_card_method()
                order = request.env['sale.order'].sudo().browse(order_id).exists()
                if method and order:
                    order.l10n_mx_edi_payment_method_id = method
        return result
