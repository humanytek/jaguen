# -*- coding: utf-8 -*-
import re

from odoo import models

# Un correo valido, sin comas, espacios ni signos de separacion.
_EMAIL_RE = re.compile(r"[^\s,;<>\"'()]+@[^\s,;<>\"'()]+\.[^\s,;<>\"'()]+")


def first_email(value):
    """Primer correo valido de un texto como "a@x.com, b@y.com" (o None si no hay)."""
    # Se quitan caracteres invisibles (p. ej. U+200B) que PayPal tampoco acepta.
    value = (value or '').encode('ascii', 'ignore').decode('utf-8')
    match = _EMAIL_RE.search(value)
    return match.group(0) if match else None


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    def _paypal_prepare_order_payload(self):
        """PayPal solo acepta UN correo en cada campo de correo. Muchos clientes de JAGUEN
        guardan varios correos en el campo "Correo" (para enviarles las facturas), y con
        eso PayPal rechaza todo el pago ("Request is not well-formed"). Aqui se le manda
        solo el primer correo valido; el dato del cliente en Odoo no se toca."""
        payload = super()._paypal_prepare_order_payload()

        def fix(container):
            if isinstance(container, dict) and 'email_address' in container:
                email = first_email(container['email_address'])
                if email:
                    container['email_address'] = email
                else:
                    container.pop('email_address')

        fix(payload.get('payment_source', {}).get('paypal'))
        for unit in payload.get('purchase_units', []):
            fix(unit.get('shipping'))
            fix(unit.get('payee'))
            display = (unit.get('payee') or {}).get('display_data') or {}
            if 'business_email' in display:
                email = first_email(display['business_email'])
                if email:
                    display['business_email'] = email
                else:
                    display.pop('business_email')
        return payload

    def _create_payment(self, **extra_create_values):
        """El pago de PayPal usa la forma de pago (04 / 28) que el cliente declaro en el pedido."""
        payment = super()._create_payment(**extra_create_values)
        if self.provider_code == 'paypal':
            method = self.sale_order_ids[:1].l10n_mx_edi_payment_method_id
            if method and method.code in ('04', '28'):
                payment.l10n_mx_edi_payment_method_id = method
        return payment
