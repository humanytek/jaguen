from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    jaguen_tyc_date = fields.Datetime(string='T&C aceptados (sitio)', readonly=True, copy=False)
    jaguen_tyc_ip = fields.Char(string='IP al aceptar T&C', readonly=True, copy=False)

    def _prepare_invoice(self):
        """Pedido pagado desde el carrito con PayPal: la factura sale PUE con forma de pago 04 / 28.

        Solo aplica si hay una transaccion de PayPal cobrada y marcada por el carrito.
        Clientes a credito (factura PPD) y pagos manuales no se tocan.
        """
        vals = super()._prepare_invoice()
        tx = self.transaction_ids.filtered(
            lambda t: t.state == 'done' and t.provider_code == 'paypal' and t.jaguen_cart_card_type)[:1]
        if tx:
            method = tx._jaguen_card_method()
            if method:
                vals['l10n_mx_edi_payment_method_id'] = method.id
            immediate = self.env.ref('account.account_payment_term_immediate', raise_if_not_found=False)
            if immediate:
                vals['invoice_payment_term_id'] = immediate.id
        return vals
