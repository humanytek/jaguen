# -*- coding: utf-8 -*-
import logging
import re

from markupsafe import Markup

from odoo import fields, models

_logger = logging.getLogger(__name__)

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

    # Marca: solo la pone el carrito web (no los links de pago del portal ni los pagos manuales).
    jaguen_cart_card_type = fields.Selection(
        [('credit', 'Crédito'), ('debit', 'Débito')],
        string="Tarjeta declarada en el carrito", copy=False)

    def _jaguen_card_method(self):
        """Forma de pago del CFDI para la tarjeta declarada: 04 (credito) o 28 (debito)."""
        self.ensure_one()
        code = {'credit': '04', 'debit': '28'}.get(self.jaguen_cart_card_type)
        Method = self.env['l10n_mx_edi.payment.method'].sudo()
        return Method.search([('code', '=', code)], limit=1) if code else Method

    def _create_payment(self, **extra_create_values):
        """Pago nacido en el carrito con PayPal: forma de pago 04 / 28 segun lo que declaro el cliente."""
        payment = super()._create_payment(**extra_create_values)
        if self.provider_code == 'paypal' and self.jaguen_cart_card_type:
            method = self._jaguen_card_method()
            if method:
                payment.l10n_mx_edi_payment_method_id = method
        return payment

    def _post_process(self):
        """Avisa al equipo cuando un cliente paga en linea (el pedido solo avisaba "se asigno a ti")."""
        pending = self.filtered(lambda t: t.state == 'done' and not t.is_post_processed)
        res = super()._post_process()
        for tx in pending:
            try:
                tx._jaguen_notify_payment()
            except Exception:  # noqa: BLE001 - un aviso nunca debe romper el cobro
                _logger.exception('No se pudo avisar del pago %s', tx.reference)
        return res

    def _jaguen_notify_payment(self):
        self.ensure_one()
        orders = self.sudo().sale_order_ids
        if not orders or self.provider_code == 'custom':
            return
        params = self.env['ir.config_parameter'].sudo()
        Users = self.env['res.users'].sudo()
        # Administracion (contabilidad): siempre se entera.
        admin_logins = [x.strip() for x in (params.get_param('jaguen_website.pay_notify_logins', 'conta.jaguen@hotmail.com') or '').split(',') if x.strip()]
        admin_partners = Users.search([('login', 'in', admin_logins)]).partner_id
        default_login = params.get_param('jaguen_website.ai_handoff_login', 'ventas.jaguen@hotmail.com')
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for order in orders:
            # Vendedor del pedido (por defecto Javier); si no tiene, el responsable por defecto.
            seller = order.user_id if order.user_id and order.user_id.active and order.user_id.share is False else Users.search([('login', '=', default_login)], limit=1)
            partners = (seller.partner_id | admin_partners)
            if not partners:
                continue
            method = order.l10n_mx_edi_payment_method_id.name if self.provider_code == 'paypal' else ''
            link = '%s/odoo/action-sale.action_orders/%s' % (base, order.id)
            body = Markup(
                '<b>💰 Pago recibido en línea</b><br/>Pedido <a href="%s">%s</a> de %s por <b>%s</b> con %s%s.<br/>'
                'Referencia del pago: %s. Falta entregar el pedido.') % (
                link, order.name, order.partner_id.name,
                '%s %.2f' % (order.currency_id.symbol or '$', self.amount), self.provider_id.sudo().name,
                (' (%s)' % method) if method else '', self.provider_reference or self.reference)
            order.sudo().message_post(
                body=body, subject='Pago recibido: %s' % order.name, message_type='comment',
                subtype_xmlid='mail.mt_comment', partner_ids=partners.ids)
