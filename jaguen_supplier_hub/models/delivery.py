from odoo import _, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _apihub_on_order_fee(self):
        """Cargo de envío por productos 'Sobre pedido' del carrito (una sola vez por pedido: el mayor entre sus proveedores).
        Docs 7j: se SUMA al envío que eligió el cliente; no es un producto ni un método de envío aparte."""
        self.ensure_one()
        providers = self.env["apihub.provider"].sudo().search([])
        group_of = {p.partner_id.id: p for p in providers if p.partner_id}
        fee = 0.0
        for line in self.order_line.filtered(lambda l: not l.is_delivery and l.product_id):
            tmpl = line.product_id.product_tmpl_id
            if tmpl.apihub_state != "on_order" and not line.apihub_on_order_qty:
                continue
            first = tmpl.sudo().seller_ids.filtered(lambda s: s.partner_id).sorted(lambda s: (s.sequence, s.id))[:1]
            provider = group_of.get(first.partner_id.id) if first else None
            fee = max(fee, provider.on_order_fee if provider else 0.0)
        return fee


class DeliveryCarrier(models.Model):
    _inherit = "delivery.carrier"

    def rate_shipment(self, order):
        res = super().rate_shipment(order)
        if res.get("success") and order and order._name == "sale.order":
            fee = order._apihub_on_order_fee()
            if fee:
                res["price"] = float(res.get("price") or 0.0) + fee
                note = _("Incluye un cargo de envío de %.2f por productos sobre pedido.", fee)
                res["warning_message"] = ("%s %s" % (res["warning_message"], note)) if res.get("warning_message") else note
        return res
