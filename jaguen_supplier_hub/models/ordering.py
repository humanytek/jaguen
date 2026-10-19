import json
import logging

import requests
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)
SYSCOM_BASE = "https://developers.syscom.mx"
LOMA_BASE = "https://apigloma.xentra.com.mx"
API_KINDS = ("syscom", "loma", "ct")


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    apihub_api_kind = fields.Char(string="Proveedor con API (ApiHub)", compute="_compute_apihub_api_kind")
    apihub_api_state = fields.Selection(
        [("none", "Sin enviar"), ("queued", "En cola (el servidor lo manda en 1-2 minutos)"), ("quoted", "Cotizada"),
         ("sent", "Enviada"), ("confirmed", "Confirmada"), ("error", "Con error")],
        string="Estado del pedido por API", default="none", copy=False, readonly=True)
    apihub_ct_step = fields.Selection([("request", "Solicitar"), ("confirm", "Confirmar")], string="Paso pendiente en CT", copy=False, readonly=True)
    apihub_api_folio = fields.Char(string="Folio del proveedor", copy=False, readonly=True)
    apihub_api_log = fields.Text(string="Última respuesta del proveedor", copy=False, readonly=True)

    @api.depends("partner_id")
    def _compute_apihub_api_kind(self):
        providers = {p.partner_id.id: p.code for p in self.env["apihub.provider"].sudo().search([("code", "in", API_KINDS)]) if p.partner_id}
        for order in self:
            order.apihub_api_kind = providers.get(order.partner_id.id, "")

    def _apihub_provider(self):
        self.ensure_one()
        provider = self.env["apihub.provider"].sudo().search([("partner_id", "=", self.partner_id.id), ("code", "in", API_KINDS)], limit=1)
        if not provider:
            raise UserError(_("Este proveedor no tiene API de pedidos en ApiHub."))
        return provider

    def action_apihub_quote(self):
        """Cotiza con el proveedor sin generar pedido (solo Syscom tiene modo de prueba)."""
        self.ensure_one()
        provider = self._apihub_provider()
        self.env["apihub.ordering"].send(self, provider, test=True)
        return True

    def action_apihub_send(self):
        """Manda el pedido por API al proveedor. Requiere que el proveedor tenga activado el candado 'Enviar pedidos por API'."""
        self.ensure_one()
        provider = self._apihub_provider()
        if not provider.api_order_enabled:
            raise UserError(_("Los pedidos por API a %s están apagados. Se encienden en ApiHub → Proveedores, con la aprobación de Javier.", provider.name))
        if self.state not in ("draft", "sent"):
            raise UserError(_("Solo se puede enviar una orden de compra en borrador."))
        if self.apihub_api_folio or self.apihub_api_state in ("sent", "confirmed", "queued"):
            raise UserError(_("Esta orden ya se envió o está en cola (folio %s).", self.apihub_api_folio or "-"))
        self.env["apihub.ordering"].send(self, provider, test=False)
        return True

    def action_apihub_ct_confirm(self):
        """CT: segundo paso. El pedido solicitado queda pendiente y CT lo cancela solo a las 48 horas si no se confirma."""
        self.ensure_one()
        provider = self._apihub_provider()
        if provider.code != "ct" or not provider.api_order_enabled:
            raise UserError(_("Solo para CT y con el envío por API encendido."))
        if self.apihub_api_state != "sent" or not self.apihub_api_folio:
            raise UserError(_("Primero hay que solicitar el pedido a CT y esperar su folio."))
        self.write({"apihub_api_state": "queued", "apihub_ct_step": "confirm"})
        self.message_post(body=_("ApiHub: se pidió confirmar el pedido %s en CT; el servidor lo manda en 1-2 minutos.", self.apihub_api_folio),
                          subtype_xmlid="mail.mt_note")
        return True


class ApihubOrdering(models.AbstractModel):
    """Pedidos al proveedor por API (docs/DECISIONES.md, secciones 7ay y 7az). Etapa B: los manda una persona con un botón."""
    _name = "apihub.ordering"
    _description = "Pedidos a proveedores por API"

    @api.model
    def _items(self, po, provider):
        """[(línea, código del proveedor, cantidad entera)] con la equivalencia aprobada de cada producto con este proveedor."""
        items = []
        for line in po.order_line.filtered(lambda l: l.product_id and not l.display_type):
            link = self.env["apihub.product.link"].sudo().search([
                ("provider_id", "=", provider.id), ("state", "=", "approved"),
                ("product_tmpl_id", "=", line.product_id.product_tmpl_id.id), ("provider_ref", "!=", False)], limit=1)
            if not link:
                raise UserError(_("%(p)s no tiene una equivalencia aprobada con %(prov)s: no se puede mandar por API.",
                                  p=line.product_id.display_name, prov=provider.name))
            qty = int(line.product_qty)
            if qty != line.product_qty or qty < 1:
                raise UserError(_("La cantidad de %s debe ser un número entero mayor a 0.", line.product_id.display_name))
            items.append((line, str(link.provider_ref).strip(), qty))
        if not items:
            raise UserError(_("La orden de compra no tiene productos."))
        return items

    @api.model
    def send(self, po, provider, test):
        po = po.sudo()
        items = self._items(po, provider)
        try:
            if provider.code == "syscom":
                state, folio, text, note = self._syscom(po, provider, items, test)
            elif provider.code == "loma":
                if test:
                    raise UserError(_("Loma no tiene modo de prueba: solo se puede enviar el pedido real."))
                state, folio, text, note = self._loma(po, provider, items)
            elif provider.code == "ct":
                if test:
                    raise UserError(_("CT no tiene modo de prueba. 'Enviar pedido por API' solicita el pedido (queda pendiente 48 horas) y después se confirma."))
                po.write({"apihub_api_state": "queued", "apihub_ct_step": "request"})
                po.message_post(body=_("ApiHub: el pedido a CT quedó en cola; el servidor lo solicita en 1-2 minutos (CT lo deja pendiente hasta confirmarlo)."),
                                subtype_xmlid="mail.mt_note")
                return True
            else:
                raise UserError(_("El proveedor %s no tiene envío por API.", provider.name))
        except UserError:
            raise
        except Exception as exc:   # noqa: BLE001
            _logger.exception("ApiHub: falló el pedido por API a %s", provider.code)
            po.write({"apihub_api_state": "error", "apihub_api_log": str(exc)[:3000]})
            po.message_post(body=_("ApiHub: falló la comunicación con %(p)s: %(e)s", p=provider.name, e=str(exc)[:300]), subtype_xmlid="mail.mt_note")
            raise UserError(_("No se pudo comunicar con %(p)s: %(e)s", p=provider.name, e=str(exc)[:300]))
        vals = {"apihub_api_state": state, "apihub_api_log": text[:6000]}
        if folio:
            vals["apihub_api_folio"] = folio
        po.write(vals)
        po.message_post(body=Markup("%s<br/>%s") % (_("ApiHub (%(p)s, %(m)s):", p=provider.name, m=_("cotización de prueba") if test else _("pedido real")),
                                                    Markup("<br/>").join(Markup("%s") % n for n in note)), subtype_xmlid="mail.mt_note")
        if state == "sent":
            po.partner_ref = folio
            try:
                po.button_confirm()
            except Exception:   # noqa: BLE001
                _logger.exception("ApiHub: no se pudo confirmar la orden de compra %s", po.name)
        return True

    # ---------------------------------------------------------------- Syscom
    @api.model
    def _syscom(self, po, provider, items, test):
        live = self.env["apihub.live"]
        body = {
            "tipo_entrega": "sucursal",
            "direccion": {"sucursal": provider.order_warehouse or "hermosillo", "atencion_a": (po.company_id.name or "JAGUEN")[:120]},
            "metodo_pago": provider.order_payment or "transferencia", "tipo_pago": "PUE", "moneda": "mxn",
            "uso_cfdi": provider.order_cfdi or "G01", "orden_compra": (po.name or "")[:40],
            "productos": [{"id": int(ref) if ref.isdigit() else ref, "cantidad": qty, "tipo": "nuevo"} for _line, ref, qty in items],
        }
        body["testmode" if test else "ordenar"] = True
        resp = requests.post(SYSCOM_BASE + "/api/v1/carrito/generar", json=body, timeout=90, headers={
            "Authorization": "Bearer " + live._syscom_token(provider, 30), "User-Agent": "Mozilla/5.0 (apihub)"})
        try:
            data = resp.json()
        except ValueError:
            raise UserError(_("Syscom respondió algo que no es JSON (HTTP %s).", resp.status_code))
        if resp.status_code != 200 or data.get("error"):
            detail = data.get("error") or data.get("detalles") or data.get("message") or data
            po.write({"apihub_api_state": "error", "apihub_api_log": json.dumps(data, ensure_ascii=False)[:6000]})
            raise UserError(_("Syscom rechazó el pedido (HTTP %(c)s): %(d)s", c=resp.status_code, d=json.dumps(detail, ensure_ascii=False)[:500]))
        resumen = data.get("resumen") or {}
        delivery = data.get("datos_entrega") or {}
        note = [_("Entrega: %(a)s, %(c)s, %(city)s", a=delivery.get("atencion_a", ""), c=delivery.get("calle", ""), city=delivery.get("ciudad", ""))]
        by_ref = {str(p.get("id")): p for p in data.get("productos") or []}
        for line, ref, qty in items:
            prod = by_ref.get(ref) or {}
            price = float(prod.get("precio_unitario") or 0)
            flag = ""
            if price and line.price_unit and abs(price - line.price_unit) / line.price_unit > 0.03:
                flag = _(" ⚠ distinto al precio de la orden de compra (%.2f)", line.price_unit)
            note.append(_("%(p)s × %(q)s: $%(u).2f c/u, sale de %(w)s%(f)s", p=line.product_id.default_code or ref, q=qty, u=price,
                          w=json.dumps(prod.get("almacenes"), ensure_ascii=False), f=flag))
        folio = str(resumen.get("folio_pedido") or "")
        if test:
            note.append(_("Es solo una cotización: no se generó ningún pedido."))
            return "quoted", False, json.dumps(data, ensure_ascii=False), note
        note.append(_("Pedido generado. Folio: %s", folio))
        return "sent", folio, json.dumps(data, ensure_ascii=False), note

    # ---------------------------------------------------------------- Loma
    @api.model
    def _loma(self, po, provider, items):
        live = self.env["apihub.live"]
        body = {
            "clave_uso_cfdi": provider.order_cfdi or "G01", "clave_metodo_pago": provider.order_payment or "PPD",
            "clave_almacen": provider.order_warehouse or "1006", "comentario": ((provider.order_comment or "") + " | " + (po.name or ""))[:250],
            "productos": [{"sku": ref, "cantidad": str(qty)} for _line, ref, qty in items],
        }
        resp = requests.post(LOMA_BASE + "/pedido", json=body, timeout=90, headers={
            "Authorization": live._credential(provider, "LOMA_API_KEY"), "User-Agent": "Mozilla/5.0 (apihub)"})
        try:
            data = resp.json()
        except ValueError:
            raise UserError(_("Loma respondió algo que no es JSON (HTTP %s).", resp.status_code))
        if resp.status_code != 200 or not data.get("resultado"):
            po.write({"apihub_api_state": "error", "apihub_api_log": json.dumps(data, ensure_ascii=False)[:6000]})
            raise UserError(_("Loma rechazó el pedido: %s", str(data.get("mensaje") or data)[:500]))
        row = (data.get("datos") or [{}])[0]
        folio = str(row.get("folio") or "")
        note = [_("Pedido guardado en Loma. Folio %(f)s, folio ERP %(e)s, estatus %(s)s, total $%(t)s.", f=folio, e=row.get("folio_erp"),
                  s=row.get("estatus"), t=row.get("total"))]
        for part in row.get("partidas") or []:
            note.append("%s × %s a $%s" % (part.get("sku"), part.get("cantidad"), part.get("precio")))
        return "sent", folio, json.dumps(data, ensure_ascii=False), note

    # ---------------------------------------------------------------- CT (lo ejecuta el servidor de Oracle: Odoo.sh no llega a la API de CT)
    @api.model
    def _ct_body(self, po, provider):
        items = self._items(po, provider)
        try:
            envio = json.loads(provider.order_ct_envio or "[]")
        except ValueError:
            raise UserError(_("El 'Envío para CT' del proveedor no es un JSON válido."))
        return {
            "idPedido": po.id, "almacen": provider.order_warehouse or "01A", "tipoPago": provider.order_payment or "99",
            "cfdi": provider.order_cfdi or "G01", "envio": envio,
            "producto": [{"cantidad": qty, "clave": ref, "precio": round(line.price_unit, 2), "moneda": "MXN"} for line, ref, qty in items],
        }

    @api.model
    def ct_pending(self):
        """Pedidos a CT en cola, para el programa del servidor: [{po_id, name, step, folio, body}]. Solo administradores."""
        if not self.env.user.has_group("base.group_system"):
            return []
        out = []
        for po in self.env["purchase.order"].sudo().search([("apihub_api_state", "=", "queued")]):
            provider = self.env["apihub.provider"].sudo().search([("partner_id", "=", po.partner_id.id), ("code", "=", "ct")], limit=1)
            if not provider or not provider.api_order_enabled:
                continue
            step = po.apihub_ct_step or "request"
            entry = {"po_id": po.id, "name": po.name, "step": step, "folio": po.apihub_api_folio or ""}
            try:
                entry["body"] = self._ct_body(po, provider) if step == "request" else {"folio": po.apihub_api_folio}
            except UserError as exc:
                self.ct_result(po.id, step, False, str(exc), "")
                continue
            out.append(entry)
        return out

    @api.model
    def ct_result(self, po_id, step, ok, text, folio):
        """Resultado que el programa del servidor reporta después de hablar con CT."""
        if not self.env.user.has_group("base.group_system"):
            return False
        po = self.env["purchase.order"].sudo().browse(po_id).exists()
        if not po:
            return False
        text = (text or "")[:6000]
        if step == "request":
            if ok:
                po.write({"apihub_api_state": "sent", "apihub_api_folio": folio, "apihub_api_log": text, "apihub_ct_step": False})
                po.message_post(body=_("ApiHub (CT): pedido solicitado, folio %s. Queda PENDIENTE: si no lo confirmas en 48 horas, CT lo cancela solo. "
                                       "Revísalo en el portal de CT y presiona 'Confirmar pedido en CT'.", folio), subtype_xmlid="mail.mt_note")
            else:
                po.write({"apihub_api_state": "error", "apihub_api_log": text, "apihub_ct_step": False})
                po.message_post(body=_("ApiHub (CT): CT no aceptó la solicitud del pedido: %s", text[:400]), subtype_xmlid="mail.mt_note")
        else:
            if ok:
                po.write({"apihub_api_state": "confirmed", "apihub_api_log": text, "apihub_ct_step": False, "partner_ref": po.apihub_api_folio})
                po.message_post(body=_("ApiHub (CT): pedido %s confirmado en CT.", po.apihub_api_folio), subtype_xmlid="mail.mt_note")
                try:
                    po.button_confirm()
                except Exception:   # noqa: BLE001
                    _logger.exception("ApiHub: no se pudo confirmar la orden de compra %s", po.name)
            else:
                po.write({"apihub_api_state": "sent", "apihub_api_log": text, "apihub_ct_step": False})
                po.message_post(body=_("ApiHub (CT): CT no confirmó el pedido %(f)s: %(t)s", f=po.apihub_api_folio, t=text[:400]), subtype_xmlid="mail.mt_note")
        return True
