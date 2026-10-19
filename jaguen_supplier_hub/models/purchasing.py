import logging
from collections import OrderedDict

from odoo import _, api, fields, models
from odoo.tools import html_escape

_logger = logging.getLogger(__name__)


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    apihub_sale_id = fields.Many2one(
        "sale.order", string="Orden de venta (ApiHub)", copy=False, index=True, ondelete="set null",
        help="La orden de venta que originó esta compra. ApiHub crea una sola compra por proveedor y por venta.")


class ApihubPurchase(models.AbstractModel):
    """Compras al proveedor al confirmar una orden de venta (docs/DECISIONES.md, sección 7ax).

    Etapa A (Javier, 2026-10-19): solo se crean órdenes de compra en BORRADOR, una por proveedor, con lo que no cubre el inventario
    propio, repartido con las mismas reglas del carrito, y una actividad para revisarlas y enviarlas. No se envía nada al proveedor."""
    _name = "apihub.purchase"
    _description = "Compras al confirmar una venta"

    @api.model
    def create_drafts(self, order, own_before):
        """own_before: {id de plantilla: inventario propio disponible ANTES de confirmar la orden}. Devuelve las órdenes de compra creadas."""
        cfg = self.env["apihub.config"].sudo().get_config()
        order = order.sudo()
        PO = self.env["purchase.order"].sudo()
        if cfg.purchase_mode == "off" or PO.search_count([("apihub_sale_id", "=", order.id)]):
            return PO
        live = self.env["apihub.live"]
        providers = {p.code: p for p in self.env["apihub.provider"].sudo().search([])}
        need = OrderedDict()
        for line in order.order_line.filtered(lambda l: l.product_id and not l.is_delivery and l.product_uom_qty > 0 and l.product_id.type == "consu"):
            entry = need.setdefault(line.product_id.product_tmpl_id.id, {"tmpl": line.product_id.product_tmpl_id, "product": line.product_id, "qty": 0})
            entry["qty"] += int(line.product_uom_qty)
        by_provider, notes = {}, []
        for entry in need.values():
            tmpl, qty = entry["tmpl"], entry["qty"]
            own = int(max(own_before.get(tmpl.id, 0), 0))
            short = max(qty - own, 0)
            label = tmpl.default_code or tmpl.name
            if not short:
                notes.append(_("%(p)s: %(q)s pieza(s), todo con inventario propio; no hay que comprar.", p=label, q=qty))
                continue
            res = live.check_product(tmpl, short, order.pricelist_id, order.id, include_own=False)
            if not res["managed"]:
                notes.append(_("%(p)s: faltan %(q)s pieza(s) y ApiHub no maneja este producto: comprar a mano.", p=label, q=short))
                continue
            taken, left = live.allocate(res, short)
            if own:
                notes.append(_("%(p)s: %(o)s pieza(s) salen del inventario propio.", p=label, o=min(own, qty)))
            for code, pieces in taken.items():
                by_provider.setdefault(code, []).append((entry["product"], pieces))
            if left:
                notes.append(_("%(p)s: faltan %(q)s pieza(s) que ningún proveedor tiene ahora: comprar a mano.", p=label, q=left))
        user = cfg.purchase_user_id or order.user_id or self.env.ref("base.user_admin")
        created = PO
        for code, lines in by_provider.items():
            provider = providers.get(code)
            if not provider or not provider.partner_id:
                notes.append(_("%(c)s: sin proveedor ligado en Odoo; comprar a mano.", c=code))
                continue
            vals = {
                "partner_id": provider.partner_id.id, "origin": order.name, "apihub_sale_id": order.id,
                "order_line": [(0, 0, {"product_id": product.id, "product_qty": pieces}) for product, pieces in lines],
            }
            if provider.purchase_delivery_note:
                vals["notes"] = "<p>%s</p>" % html_escape(provider.purchase_delivery_note)
            po = PO.create(vals)
            po.activity_schedule("mail.mail_activity_data_todo", user_id=user.id,
                                 summary=_("Revisar y enviar a %(p)s (venta %(o)s)", p=provider.name, o=order.name))
            created |= po
            notes.append(_("%(po)s (%(p)s): %(l)s", po=po.name, p=provider.name,
                           l=", ".join("%s × %s" % (product.default_code or product.name, pieces) for product, pieces in lines)))
        if notes or created:
            body = _("ApiHub: compras por esta venta (borradores, no se envió nada al proveedor):") + "<br/>" + "<br/>".join(html_escape(n) for n in notes)
            order.message_post(body=body, subtype_xmlid="mail.mt_note")
        return created

    @api.model
    def test_confirm_plan(self, order_id):
        """Prueba manual (solo administradores): crea las compras de una orden ya confirmada como si se acabara de confirmar,
        tomando como inventario propio previo lo que hoy está disponible más lo que la orden reservó."""
        if not self.env.user.has_group("base.group_system"):
            return []
        order = self.env["sale.order"].browse(order_id)
        own_before = {}
        for line in order.order_line.filtered(lambda l: l.product_id and not l.is_delivery):
            tmpl = line.product_id.product_tmpl_id
            own_before[tmpl.id] = self.env["apihub.live"].sudo()._own_free(tmpl)
        return self.create_drafts(order, own_before).mapped("name")
