# -*- coding: utf-8 -*-
import logging

from markupsafe import Markup, escape

from odoo import models

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _message_auto_subscribe_notify(self, partner_ids, template):
        """Un carrito del sitio (pedido en borrador sin firma) se asigna al vendedor del sitio al crearse, y Odoo le
        mandaba "Le asignaron al Orden de venta ..." por cada carrito, aunque nadie hubiera comprado. Esos avisos se
        omiten; el aviso real llega cuando el cliente firma o paga (ver action_confirm)."""
        carts = self.filtered(lambda o: o.website_id and o.state in ('draft', 'sent') and not o.signature)
        return super(SaleOrder, self - carts)._message_auto_subscribe_notify(partner_ids, template)

    def action_confirm(self):
        candidates = self.filtered(lambda o: o.website_id and o.state in ('draft', 'sent'))
        res = super().action_confirm()
        for order in candidates.filtered(lambda o: o.state == 'sale'):
            paid = order.transaction_ids.filtered(lambda t: t.state in ('done', 'authorized'))
            # Si el cliente firmo, Odoo ya avisa solo ("Orden firmada por ..."): un segundo aviso seria ruido.
            # Este aviso es para el pedido pagado en linea sin firma.
            if paid and not order.signature:
                order._jaguen_notify_web_order_confirmed(signed=False)
        return res

    def _jaguen_notify_web_order_confirmed(self, signed):
        """Aviso al vendedor cuando un cliente acepta y firma la cotizacion (o paga en linea) y se crea la orden de venta."""
        self.ensure_one()
        user = self.user_id
        if not user or not user.partner_id:
            return
        how = 'aceptó y firmó la cotización' if signed else 'pagó en línea'
        try:
            with self.env.cr.savepoint():
                self.message_notify(
                    partner_ids=user.partner_id.ids,
                    subject='Orden de venta %s confirmada' % self.name,
                    body=Markup('%s <b>%s</b> (%s). Total: %s %s.') % (
                        escape('El cliente'), self.partner_id.display_name, how,
                        '{:,.2f}'.format(self.amount_total), self.currency_id.name),
                )
        except Exception:  # un aviso nunca debe impedir confirmar el pedido
            _logger.exception('No se pudo avisar de la orden %s', self.name)
