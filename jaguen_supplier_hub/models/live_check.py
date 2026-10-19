import logging
import math
import time
from datetime import timedelta

from markupsafe import Markup

import requests

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

_logger = logging.getLogger(__name__)

_CACHE = {}   # por proceso: clave -> (vence, valor). Evita repetir la misma consulta en cada paso del carrito.
_FAILED = object()
SYSCOM_BASE = "https://developers.syscom.mx"
LOMA_BASE = "https://apigloma.xentra.com.mx"
CT_BASE = "http://connect.ctonline.mx:3001"
NEAR_LIVE_SECONDS = 5400   # existencia revisada por el robot hace menos de hora y media (CT y Exel se revisan cada hora)


def own_free(tmpl):
    """Inventario propio disponible de un producto (lo que hay menos lo ya apartado). En Odoo 18 `free_qty` existe en la variante,
    no en la plantilla."""
    return int(sum(max(v.free_qty, 0) for v in tmpl.sudo().product_variant_ids))


def _cached(key, ttl, loader):
    """Resultado en memoria por `ttl` segundos. Un fallo se recuerda 3 minutos para no esperar el tiempo límite en cada paso."""
    now = time.time()
    hit = _CACHE.get(key)
    if hit and hit[0] > now:
        if hit[1] is _FAILED:
            raise RuntimeError(hit[2])
        return hit[1]
    try:
        value = loader()
    except Exception as exc:   # noqa: BLE001 - cualquier fallo del proveedor se trata igual
        _CACHE[key] = (now + 180, _FAILED, str(exc)[:200])
        raise
    _CACHE[key] = (now + ttl, value)
    return value


class ApihubLive(models.AbstractModel):
    """Verificación de existencia en vivo al carrito (docs/DECISIONES.md, sección 7e).

    Consulta al proveedor en el momento de agregar al carrito y antes de pagar. Syscom, Loma y CT tienen API; Exel e Ingram
    no (siguen con el dato del archivo diario). Si un proveedor no responde, no se bloquea la compra: se usa el dato del
    archivo y se deja la nota 'verificar disponibilidad'."""
    _name = "apihub.live"
    _description = "Verificación de existencia en vivo"

    # ------------------------------------------------------------------ conexión
    @api.model
    def _credential(self, provider, key):
        cred = provider.sudo().credential_ids.filtered(lambda c: c.key == key)[:1]
        return (cred.value or "").strip() if cred else ""

    @api.model
    def _http_json(self, method, url, headers, timeout, body=None):
        resp = requests.request(method, url, headers=dict(headers, **{"User-Agent": "Mozilla/5.0 (apihub)"}), json=body, timeout=timeout)
        if resp.status_code == 401:
            raise PermissionError("401")
        resp.raise_for_status()
        return resp.json()

    @api.model
    def _syscom_token(self, provider, timeout):
        def load():
            data = requests.post(SYSCOM_BASE + "/oauth/token", data={
                "grant_type": "client_credentials", "client_id": self._credential(provider, "SYSCOM_CLIENT_ID"),
                "client_secret": self._credential(provider, "SYSCOM_CLIENT_SECRET")},
                headers={"User-Agent": "Mozilla/5.0 (apihub)"}, timeout=timeout)
            data.raise_for_status()
            return data.json()["access_token"]
        return _cached(("syscom_token", provider.id), 3000, load)

    @api.model
    def _syscom_stock(self, provider, ref, timeout):
        def token():
            return self._syscom_token(provider, timeout)

        for attempt in (0, 1):
            try:
                data = self._http_json("GET", "%s/api/v1/productos/%s?inventarios=true" % (SYSCOM_BASE, ref),
                                       {"Authorization": "Bearer " + token()}, timeout)
                break
            except PermissionError:
                _CACHE.pop(("syscom_token", provider.id), None)
                if attempt:
                    raise
        existence = data.get("existencia") or {}
        detail = (existence.get("detalle") or {}).get("nuevo") or {}
        by_wh = {str(k).lower(): int(v or 0) for k, v in detail.items() if v}
        return by_wh, int(existence.get("nuevo") or data.get("total_existencia") or 0)

    @api.model
    def _loma_stock(self, provider, ref, timeout):
        """Loma no consulta por producto: baja el catálogo con existencia por almacén (unos 2 MB) y lo guarda 5 minutos."""
        def load():
            key = self._credential(provider, "LOMA_API_KEY")
            data = self._http_json("GET", LOMA_BASE + "/productos_almacenes?sin_stock=true&moneda=MXN",
                                   {"Authorization": key}, max(timeout, 20))
            if not data.get("resultado"):
                raise RuntimeError("Loma respondió resultado=false")
            index = {}
            for row in data.get("datos") or []:
                by_wh = {str(w.get("almacen_clave")).lower(): int(w.get("stock") or 0)
                         for w in row.get("almacenes") or [] if int(w.get("stock") or 0) > 0}
                total = int(float(row.get("stock") or 0))
                for name in {str(row.get("referencia") or ""), str(row.get("sku") or "")} - {""}:
                    index[name] = (by_wh, total)
            return index
        index = _cached(("loma_catalog", provider.id), 300, load)
        return index.get(ref, ({}, 0))

    @api.model
    def _ct_stock(self, provider, ref, timeout):
        base = (self._credential(provider, "CT_API_BASE") or CT_BASE).rstrip("/")

        def token():
            def load():
                data = self._http_json("POST", base + "/cliente/token", {}, timeout, body={
                    "email": self._credential(provider, "CT_API_EMAIL"), "cliente": self._credential(provider, "CT_API_CLIENT"),
                    "rfc": self._credential(provider, "CT_API_RFC")})
                return data["token"]
            return _cached(("ct_token", provider.id), 1500, load)

        for attempt in (0, 1):
            try:
                data = self._http_json("GET", "%s/existencia/%s" % (base, ref), {"x-auth": token()}, timeout)
                break
            except PermissionError:
                _CACHE.pop(("ct_token", provider.id), None)
                if attempt:
                    raise
        by_wh = {}
        for code, node in (data or {}).items():
            if isinstance(node, dict) and node.get("existencia"):
                by_wh[str(code).lower()] = int(node["existencia"])
        return by_wh, sum(by_wh.values())

    LIVE_ADAPTERS = {"syscom": "_syscom_stock", "loma": "_loma_stock", "ct": "_ct_stock"}

    # ------------------------------------------------------------------ existencia de un proveedor
    @api.model
    def _provider_stock(self, provider, link, rules, cfg):
        """(local, nacional, origen) donde origen es 'vivo', 'archivo' o 'archivo (sin respuesta del proveedor)'."""
        adapter = self.LIVE_ADAPTERS.get(provider.code)
        if adapter and provider.live_check and link.provider_ref and self._credential(provider, {"syscom": "SYSCOM_CLIENT_ID", "loma": "LOMA_API_KEY", "ct": "CT_API_EMAIL"}[provider.code]):
            try:
                ref, timeout = str(link.provider_ref).strip(), cfg.live_timeout or 6
                by_wh, national = _cached(("stock", provider.id, ref), 60, lambda: getattr(self, adapter)(provider, ref, timeout))
                codes = {(r.code or "").lower() for r in rules}
                local = national if "*" in codes else sum(q for c, q in by_wh.items() if c in codes)
                return local, national, "vivo"
            except Exception as exc:   # noqa: BLE001
                _logger.warning("ApiHub: consulta en vivo a %s falló (%s); se usa el dato del archivo.", provider.code, exc)
                origin = "archivo (sin respuesta del proveedor: %s)" % str(exc)[:150]
        else:
            origin = "archivo"
        near = link.stock_at and (fields.Datetime.now() - link.stock_at).total_seconds() <= NEAR_LIVE_SECONDS
        if near:
            # el robot de existencia (CT, Exel) lo revisó hace menos de hora y media: se confía igual que en vivo (sin mínimo)
            minutes = int((fields.Datetime.now() - link.stock_at).total_seconds() // 60)
            local = link.stock_national if any(r.code == "*" for r in rules) else link.stock_local
            return local, link.stock_national, "casi en vivo, hace %d min" % minutes
        today = fields.Date.context_today(self)
        fresh = link.stock_date and (today - link.stock_date).days <= math.ceil((provider.max_data_age_hours or 24) / 24.0)
        if not fresh:
            return 0, 0, origin + ", dato viejo"
        # Dato del archivo: se aplica el mismo mínimo que la publicación (docs 7e: sin consulta en vivo el mínimo se queda alto)
        # y "*" (Ingram) significa que cualquier almacén cuenta como local.
        threshold = (rules[0].min_stock_override if rules and rules[0].min_stock_override > 0 else provider.min_stock) or 1
        local = link.stock_national if any(r.code == "*" for r in rules) else link.stock_local
        national = link.stock_national
        return (local if local >= threshold else 0), (national if national >= (provider.min_stock or 1) else 0), origin

    # ------------------------------------------------------------------ revisión de un producto
    @api.model
    def _reserved(self, tmpl, cfg, exclude_order_id=False):
        """(piezas apartadas, de ellas las de entrega inmediata). Aún no se las compramos al proveedor, así que su existencia
        todavía no refleja esas ventas. Apartan: (1) órdenes de venta confirmadas de las últimas `live_reserve_hours` horas que no se
        han entregado; (2) compras del sitio que siguen como cotización pero llegaron a "Gracias por su orden" hace menos de
        `live_hold_minutes` minutos (pasado el tiempo se liberan solas). Un carrito sin terminar no aparta nada."""
        now = fields.Datetime.now()
        domains = []
        if cfg.live_reserve_hours:
            domains.append([("order_id.state", "=", "sale"), ("order_id.date_order", ">=", now - timedelta(hours=cfg.live_reserve_hours))])
        if cfg.live_hold_minutes:
            domains.append([("order_id.state", "=", "sent"), ("order_id.website_id", "!=", False),
                            ("order_id.apihub_held_at", ">=", now - timedelta(minutes=cfg.live_hold_minutes))])
        pending = immediate = 0
        for extra in domains:
            domain = [("product_id.product_tmpl_id", "=", tmpl.id), ("is_delivery", "=", False)] + extra
            if exclude_order_id:
                domain.append(("order_id", "!=", exclude_order_id))
            for line in self.env["sale.order.line"].sudo().search(domain):
                left = max(int(line.product_uom_qty - line.qty_delivered), 0)
                pending += left
                immediate += left - min(line.apihub_on_order_qty, left)
        return pending, immediate

    @api.model
    def check_product(self, tmpl, qty, pricelist=None, exclude_order_id=False, include_own=True):
        """Revisa si se pueden surtir `qty` piezas del producto. Devuelve un diccionario:
        managed (si ApiHub lo maneja), ok, max_qty, assigned [(proveedor, piezas)], unverified [proveedores], message, detail."""
        cfg = self.env["apihub.config"].sudo().get_config()
        tmpl = tmpl.sudo()
        providers = self.env["apihub.provider"].sudo().search([])
        group_of = {p.partner_id.id: p for p in providers if p.partner_id}
        links = self.env["apihub.product.link"].sudo().search([("product_tmpl_id", "=", tmpl.id), ("state", "=", "approved")])
        lines = tmpl.seller_ids.filtered(lambda s: s.partner_id).sorted(lambda s: (s.sequence, s.id))
        result = {"managed": False, "ok": True, "max_qty": qty, "assigned": [], "unverified": [], "message": "", "detail": []}
        if (not links or not lines or tmpl.apihub_state not in ("local", "on_order")
                or not all(s.partner_id.id in group_of and group_of[s.partner_id.id].has_stock_data for s in lines)):
            return result
        result["managed"] = True
        basis_local = tmpl.apihub_state == "local"
        rules_of = {}
        for rule in self.env["apihub.warehouse.rule"].sudo().search([("active", "=", True), ("counts_for_publication", "=", True)]):
            rules_of.setdefault(rule.provider_id.id, []).append(rule)
        price = 0.0
        if pricelist:
            try:
                price = pricelist.sudo()._get_product_price(tmpl.product_variant_id, qty)
            except Exception:   # noqa: BLE001
                price = 0.0
        tech = (tmpl.categ_id.complete_name or "").startswith("Computo y Tecnologia") if tmpl.categ_id else False
        order_of = {}
        for idx, line in enumerate(lines):
            order_of.setdefault(group_of[line.partner_id.id].id, idx)
        first_provider = group_of[lines[0].partner_id.id]
        # inventario propio (disponible = lo que hay menos lo ya apartado por otras órdenes): cuenta como entrega inmediata y se usa primero
        own = own_free(tmpl) if include_own else 0
        result["own"] = own
        remaining, remaining_nat, local_total, national_total = max(qty - own, 0), max(qty - own, 0), 0, 0
        result["assigned_national"] = []
        if own > 0:
            result["assigned"].append(("inventario propio", min(own, qty)))
            result["assigned_national"].append(("inventario propio", min(own, qty)))
            result["detail"].append("inventario propio: %s pieza(s) disponibles" % own)
        for link in sorted(links, key=lambda l: order_of.get(l.provider_id.id, 99)):
            provider = link.provider_id
            rules = rules_of.get(provider.id, [])
            local, national, origin = self._provider_stock(provider, link, rules, cfg)
            note = "%s: %s pieza(s) locales y %s en total [%s]" % (provider.code, local, national, origin)
            if "sin respuesta" in origin:
                result["unverified"].append(provider.code)
            if (local > 0 or national > 0) and provider != first_provider and price:
                cost = link.cost_provider or 0.0
                free = any(r.free_shipping for r in rules) and local > 0
                if tech and provider.freight_only_tech and not free:
                    cost += provider.freight_amount or 0.0
                margin = (price - cost) / price * 100.0 if cost else 100.0
                if margin < (cfg.min_margin_pct or 0.0):
                    note += " - no cuenta: margen %.1f%% menor al mínimo" % margin
                    local = national = 0
            result["detail"].append(note)
            result.setdefault("per_provider", []).append((provider.code, local, national))
            local_total += local
            national_total += national
            if basis_local and local > 0 and remaining > 0:
                take = min(local, remaining)
                result["assigned"].append((provider.code, take))
                remaining -= take
            if national > 0 and remaining_nat > 0:
                take = min(national, remaining_nat)
                result["assigned_national"].append((provider.code, take))
                remaining_nat -= take
            if not basis_local and national > 0 and remaining_nat >= 0:
                result["assigned"] = result["assigned_national"]
        reserved_now, reserved_local = self._reserved(tmpl, cfg, exclude_order_id)
        if reserved_now:
            result["detail"].append("Apartadas por otras ventas: %s pieza(s), %s de entrega inmediata" % (reserved_now, reserved_local))
            local_total = max(0, local_total - reserved_local)
            national_total = max(0, national_total - reserved_now)
        local_total += own
        national_total += own
        total = local_total if basis_local else national_total
        result["local_total"], result["national_total"], result["basis_local"] = local_total, national_total, basis_local
        result["max_qty"] = min(qty, total)
        if total <= 0 and national_total <= 0:
            result["ok"], result["message"] = False, _("Este producto ya no está disponible.")
        elif total < qty:
            result["ok"] = False
            if basis_local and national_total > local_total:
                target = min(qty, national_total)
                result["offer"] = {"local": local_total, "target": target, "extra": target - local_total}
                result["message"] = _("Solo hay %s pieza(s) para entrega inmediata; hay más disponibles sobre pedido.", local_total)
            else:
                result["message"] = _("Solo hay %s pieza(s) disponibles de este producto; ajustamos la cantidad.", total)
        return result

    @api.model
    def _own_free(self, tmpl):
        return own_free(tmpl)

    @api.model
    def allocate(self, res, qty):
        """Reparte `qty` piezas entre los proveedores con el resultado de check_product(include_own=False): primero lo que hay local, por el
        orden de proveedores; el resto de la existencia total que queda. Devuelve ({proveedor: piezas}, piezas sin proveedor)."""
        taken, left = {}, qty
        for code, local, _national in res.get("per_provider", []):
            take = min(local, left)
            if take > 0:
                taken[code] = taken.get(code, 0) + take
                left -= take
        for code, _local, national in res.get("per_provider", []):
            take = min(max(national - taken.get(code, 0), 0), left)
            if take > 0:
                taken[code] = taken.get(code, 0) + take
                left -= take
        return taken, left

    @api.model
    def _log(self, cfg, order, tmpl, qty, res, ms, step):
        try:
            outcome = ("sin_verificar" if res["unverified"] else "bloqueado" if not res["ok"] else "ok") if res["managed"] else "no_aplica"
            self.env["apihub.live.log"].sudo().create({
                "order_id": order.id if order and order.id else False, "product_tmpl_id": tmpl.id, "qty": qty, "step": step,
                "mode": cfg.live_mode, "outcome": outcome, "ms": ms,
                "detail": ("\n".join(res["detail"] + [res["message"], "Asignado: %s" % (res["assigned"],)]) if res["managed"] else False)})
        except Exception:   # noqa: BLE001 - el registro nunca debe romper el carrito
            _logger.exception("ApiHub: no se pudo guardar el registro de verificación en vivo")

    # ------------------------------------------------------------------ puntos de entrada
    @api.model
    def cart_update_check(self, order, product_id, qty):
        """Al agregar o subir cantidad. Devuelve (cantidad, aviso); sin cambios si el modo está apagado o en observación.
        Si piden más de lo que hay para entrega inmediata y el resto está sobre pedido, no lo agrega: deja una oferta para
        que el cliente la acepte o la rechace en el carrito (docs 7au)."""
        cfg = self.env["apihub.config"].sudo().get_config()
        if cfg.live_mode == "off":
            return qty, ""
        started = time.time()
        try:
            tmpl = self.env["product.product"].sudo().browse(product_id).product_tmpl_id
            res = self.check_product(tmpl, qty, order.pricelist_id, order.id)
            self._log(cfg, order, tmpl, qty, res, int((time.time() - started) * 1000), "carrito")
            if cfg.live_mode == "on" and res["managed"]:
                return self._apply_result(order, product_id, tmpl, qty, res)
        except Exception:   # noqa: BLE001 - ante cualquier error la compra sigue
            _logger.exception("ApiHub: verificación en vivo del carrito falló; se deja pasar")
        return qty, ""

    @api.model
    def _apply_result(self, order, product_id, tmpl, qty, res):
        offers = order.sudo().apihub_offer_ids.filtered(lambda o: o.product_id.id == product_id)
        if res["ok"]:
            offers.filtered(lambda o: o.state == "pending").unlink()
            return qty, ""
        offer = res.get("offer")
        if not offer:
            return res["max_qty"], res["message"]
        accepted = offers.filtered(lambda o: o.state == "accepted")[:1]
        if accepted:
            # el cliente ya aceptó las condiciones de "sobre pedido" para este producto: si sube la cantidad no se le vuelve a preguntar
            if offer["target"] > accepted.requested_qty:
                accepted.write({"requested_qty": offer["target"], "extra_qty": offer["target"] - accepted.local_qty})
            if offer["target"] < qty:
                return offer["target"], _("Solo hay %s pieza(s) disponibles de este producto; ajustamos la cantidad.", offer["target"])
            return qty, ""
        first = tmpl.sudo().seller_ids.filtered(lambda s: s.partner_id).sorted(lambda s: (s.sequence, s.id))[:1]
        provider = next((p for p in self.env["apihub.provider"].sudo().search([]) if first and p.partner_id == first.partner_id), None)
        unit = 0.0
        try:
            product = self.env["product.product"].sudo().browse(product_id)
            base = order.pricelist_id.sudo()._get_product_price(product, 1.0)
            taxes = order.fiscal_position_id.sudo().map_tax(product.taxes_id.filtered(lambda t: t.company_id == order.company_id))
            unit = taxes.compute_all(base, order.currency_id, 1.0, product=product, partner=order.partner_shipping_id)["total_included"]
        except Exception:   # noqa: BLE001 - sin precio el aviso sale igual, sin el importe
            _logger.exception("ApiHub: no se pudo calcular el precio por pieza de la oferta")
        vals = {"requested_qty": offer["target"], "local_qty": offer["local"], "extra_qty": offer["extra"],
                "fee": provider.on_order_fee if provider else 0.0, "unit_price_incl": unit, "state": "pending"}
        if not offer["local"]:
            # sin piezas de entrega inmediata el producto se vende como cualquiera "sobre pedido": se agrega directo y se avisa
            # (sin renglón en el carrito no habría dónde mostrar la oferta y Odoo descartaría el carrito)
            vals["state"] = "accepted"
        pending = offers.filtered(lambda o: o.state == "pending")[:1]
        if pending:
            pending.write(vals)
        else:
            self.env["apihub.cart.offer"].sudo().create(dict(vals, order_id=order.id, product_id=product_id))
        if not offer["local"]:
            cfg = self.env["apihub.config"].sudo().get_config()
            return offer["target"], _("Por el momento no hay piezas para entrega inmediata; este producto se surte sobre pedido: entrega en %(plazo)s "
                                      "y un único cargo de envío de $%(fee).2f + IVA por orden.", plazo=cfg.on_order_text or "", fee=vals["fee"])
        return offer["local"], _("Hay piezas disponibles sobre pedido: revisa la opción que aparece en tu carrito.")

    @api.model
    def order_check(self, order, step="pago"):
        """Antes de pagar: revisa todas las líneas del pedido. Devuelve la lista de problemas [(línea, mensaje)]; en modo
        'observación' solo registra. Deja una nota en el pedido si hay que verificar algo o se asignó otro proveedor."""
        cfg = self.env["apihub.config"].sudo().get_config()
        if cfg.live_mode == "off":
            return []
        problems, notes = [], []
        for line in order.sudo().order_line.filtered(lambda l: l.product_id and not l.is_delivery and l.product_uom_qty > 0):
            started = time.time()
            try:
                tmpl = line.product_id.product_tmpl_id
                res = self.check_product(tmpl, int(line.product_uom_qty), order.pricelist_id, order.id)
                self._log(cfg, order, tmpl, int(line.product_uom_qty), res, int((time.time() - started) * 1000), step)
            except Exception:   # noqa: BLE001
                _logger.exception("ApiHub: verificación en vivo antes de pagar falló; se deja pasar")
                continue
            if not res["managed"]:
                continue
            accepted = order.sudo().apihub_offer_ids.filtered(lambda o: o.product_id == line.product_id and o.state == "accepted")[:1]
            if not res["ok"] and res.get("offer") and accepted and res["offer"]["target"] == int(line.product_uom_qty) <= accepted.requested_qty:
                taken = dict(res["assigned"])
                extra_left, extra_from = res["offer"]["extra"], []
                for code, _local, national in res.get("per_provider", []):
                    take = min(max(national - taken.get(code, 0), 0), extra_left)
                    if take:
                        extra_from.append("%s %s" % (code, take))
                        extra_left -= take
                notes.append("%s: %s de entrega inmediata (%s) y %s sobre pedido (%s), aceptado por el cliente." % (
                    tmpl.default_code, res["offer"]["local"], ", ".join("%s %s" % (c, q) for c, q in res["assigned"]),
                    res["offer"]["extra"], ", ".join(extra_from)))
                continue
            if not res["ok"]:
                # en este paso no se ajusta nada solo: el cliente debe volver al carrito
                if res.get("offer"):
                    message = _("Tu pedido incluye piezas sobre pedido que aún no aceptas. Regresa al carrito para revisarlo.")
                elif res["max_qty"] > 0:
                    message = _("Solo hay %s pieza(s) disponibles de este producto. Regresa al carrito y ajusta la cantidad.", res["max_qty"])
                else:
                    message = _("Este producto ya no está disponible. Regresa al carrito y quítalo.")
                problems.append((line, message))
            else:
                first = tmpl.sudo().seller_ids.filtered(lambda s: s.partner_id).sorted(lambda s: (s.sequence, s.id))[:1]
                p1 = next((p for p in self.env["apihub.provider"].sudo().search([]) if first and p.partner_id == first.partner_id), None)
                if res["assigned"] and p1 and res["assigned"][0][0] != p1.code:
                    notes.append("%s: pedir a %s (el Proveedor 1, %s, no tiene)." % (tmpl.default_code, res["assigned"][0][0], p1.code))
            if res["unverified"]:
                notes.append("%s: verificar disponibilidad con %s (no respondió)." % (tmpl.default_code, ", ".join(res["unverified"])))
        if notes:
            text = "\n".join(notes)
            if order.sudo().apihub_live_note != text:
                order.sudo().write({"apihub_live_note": text})
                order.sudo().message_post(body=Markup("%s<br/>%s") % (_("ApiHub, verificación en vivo:"), Markup("<br/>").join(Markup("%s") % n for n in notes)),
                                          subtype_xmlid="mail.mt_note")
        return problems if cfg.live_mode == "on" else []

    @api.model
    def test_order(self, order_id, step="pago"):
        """Prueba manual: qué problemas daría la verificación antes de pagar para un pedido (solo administradores)."""
        if not self.env.user.has_group("base.group_system"):
            raise AccessError(_("Solo los administradores pueden probar la verificación en vivo."))
        order = self.env["sale.order"].browse(order_id)
        return [[line.product_id.display_name, message] for line, message in self.order_check(order, step)]

    @api.model
    def test_product(self, tmpl_id, qty=1):
        """Prueba manual desde Odoo: qué diría la verificación en vivo de este producto (solo administradores)."""
        if not self.env.user.has_group("base.group_system"):
            raise AccessError(_("Solo los administradores pueden probar la verificación en vivo."))
        tmpl = self.env["product.template"].browse(tmpl_id)
        pricelist = self.env["apihub.config"].sudo().get_config().public_pricelist_id
        res = self.check_product(tmpl, qty, pricelist)
        res["assigned"] = [list(a) for a in res["assigned"]]
        return res


class ApihubLiveLog(models.Model):
    _name = "apihub.live.log"
    _description = "Registro de verificaciones en vivo"
    _order = "id desc"

    create_date = fields.Datetime(string="Fecha", readonly=True)
    order_id = fields.Many2one("sale.order", string="Pedido", ondelete="set null")
    product_tmpl_id = fields.Many2one("product.template", string="Producto", ondelete="cascade")
    qty = fields.Integer(string="Cantidad pedida")
    step = fields.Char(string="Paso")
    mode = fields.Char(string="Modo")
    outcome = fields.Selection(
        [("ok", "Disponible"), ("bloqueado", "No disponible o menos piezas"), ("sin_verificar", "Sin respuesta del proveedor"),
         ("no_aplica", "No lo maneja ApiHub")], string="Resultado")
    ms = fields.Integer(string="Milisegundos")
    detail = fields.Text(string="Detalle")


class ApihubCartOffer(models.Model):
    """Oferta al cliente cuando pide más piezas de las que hay para entrega inmediata y el resto está sobre pedido."""
    _name = "apihub.cart.offer"
    _description = "Oferta de piezas sobre pedido en el carrito"

    order_id = fields.Many2one("sale.order", string="Pedido", required=True, ondelete="cascade", index=True)
    product_id = fields.Many2one("product.product", string="Producto", required=True, ondelete="cascade")
    requested_qty = fields.Integer(string="Cantidad total pedida")
    local_qty = fields.Integer(string="Entrega inmediata")
    extra_qty = fields.Integer(string="Sobre pedido")
    fee = fields.Float(string="Cargo de envío sobre pedido (sin IVA)")
    unit_price_incl = fields.Float(string="Precio por pieza con IVA", digits=(12, 2))
    state = fields.Selection([("pending", "Pendiente"), ("accepted", "Aceptada")], default="pending", required=True)

    def action_accept(self):
        """El cliente acepta recibir en dos partes: se sube la línea a la cantidad pedida (ya con la oferta aceptada)."""
        for offer in self:
            order = offer.order_id
            if order.state != "draft":
                continue
            offer.state = "accepted"
            order._cart_update(product_id=offer.product_id.id, set_qty=offer.requested_qty)
        return True

    def action_decline(self):
        self.unlink()
        return True

    def action_remove(self):
        """El cliente quita las piezas sobre pedido que había aceptado: la línea vuelve a la cantidad de entrega inmediata."""
        for offer in self:
            order, product, local = offer.order_id, offer.product_id, offer.local_qty
            offer.unlink()
            if order.state == "draft":
                # add_qty=None: con el valor por defecto (0) Odoo ignora set_qty=0 y la línea no se quita
                order._cart_update(product_id=product.id, set_qty=local, add_qty=None)
        return True


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    apihub_on_order_qty = fields.Integer(
        string="Piezas sobre pedido (ApiHub)", copy=False,
        help="Piezas de esta línea que el cliente aceptó recibir sobre pedido (el resto es de entrega inmediata).")


class SaleOrder(models.Model):
    _inherit = "sale.order"

    apihub_held_at = fields.Datetime(string="Piezas apartadas desde (ApiHub)", copy=False, readonly=True)
    apihub_offer_ids = fields.One2many("apihub.cart.offer", "order_id", string="Ofertas de piezas sobre pedido")
    apihub_live_note = fields.Text(string="Nota de verificación en vivo (ApiHub)", copy=False, readonly=True)

    def _verify_updated_quantity(self, order_line, product_id, new_qty, **kwargs):
        new_qty, warning = super()._verify_updated_quantity(order_line, product_id, new_qty, **kwargs)
        if new_qty > 0 and (not order_line or new_qty > order_line.product_uom_qty):
            live_qty, live_warning = self.env["apihub.live"].cart_update_check(self, product_id, new_qty)
            if live_warning:
                return live_qty, live_warning
        return new_qty, warning

    def action_quotation_sent(self):
        res = super().action_quotation_sent()
        now = fields.Datetime.now()
        for order in self.filtered("website_id"):
            order.sudo().apihub_held_at = now   # la compra del sitio aparta sus piezas desde aquí (docs 7av)
        return res

    def action_confirm(self):
        late = self.filtered(lambda o: o.website_id and o.state in ("draft", "sent"))
        # inventario propio disponible ANTES de confirmar (al confirmar se reserva y baja): sirve para saber qué hay que comprar
        own_before = {}
        for order in self:
            own_before[order.id] = {l.product_id.product_tmpl_id.id: own_free(l.product_id.product_tmpl_id)
                                    for l in order.order_line if l.product_id and not l.is_delivery}
        res = super().action_confirm()
        for order in self:
            try:
                self.env["apihub.purchase"].sudo().create_drafts(order, own_before.get(order.id, {}))
            except Exception:   # noqa: BLE001 - nunca debe impedir confirmar la orden
                _logger.exception("ApiHub: no se pudieron crear las compras de la orden %s", order.name)
                order.sudo().message_post(body=_("ApiHub: no se pudieron crear las órdenes de compra de esta venta; hazlas a mano."), subtype_xmlid="mail.mt_note")
        for order in late:
            try:
                problems = self.env["apihub.live"].sudo().order_check(order, "confirmar-venta")
                if problems:
                    order.sudo().message_post(body=Markup("%s<br/>%s") % (
                        _("ApiHub: al confirmar esta orden ya no había existencia suficiente (las piezas apartadas se liberaron o el proveedor "
                          "las agotó). Verifica antes de pedir:"),
                        Markup("<br/>").join(Markup("%s: %s") % (line.product_id.display_name, msg) for line, msg in problems)),
                        subtype_xmlid="mail.mt_note")
            except Exception:   # noqa: BLE001 - nunca debe impedir confirmar la orden
                _logger.exception("ApiHub: revisión al confirmar la orden falló")
        return res

    def _apihub_hold_minutes(self):
        """Minutos que se apartan las piezas de esta compra del sitio (para el aviso de 'Gracias por su orden'), 0 si no aplica."""
        self.ensure_one()
        cfg = self.env["apihub.config"].sudo().get_config()
        return cfg.live_hold_minutes if (cfg.live_mode == "on" and self.state == "sent" and self.apihub_held_at) else 0

    def _apihub_hold_seconds_left(self):
        """Segundos que le quedan al apartado de esta compra del sitio (0 si ya venció o no aplica)."""
        self.ensure_one()
        minutes = self._apihub_hold_minutes()
        if not minutes:
            return 0
        return max(int(minutes * 60 - (fields.Datetime.now() - self.apihub_held_at).total_seconds()), 0)

    def _apihub_on_order_text(self):
        return self.env["apihub.config"].sudo().get_config().on_order_text or ""

    def _cart_update_order_line(self, product_id, quantity, order_line, **kwargs):
        line = super()._cart_update_order_line(product_id, quantity, order_line, **kwargs)
        if not line:
            # se quitó la línea: ya no tiene sentido la oferta de ese producto
            self.sudo().apihub_offer_ids.filtered(lambda o: o.product_id.id == product_id).unlink()
        if line:
            offer = self.sudo().apihub_offer_ids.filtered(lambda o: o.product_id.id == line.product_id.id and o.state == "accepted")[:1]
            extra = max(0, int(line.product_uom_qty) - offer.local_qty) if offer else 0
            if line.apihub_on_order_qty != extra:
                line.sudo().apihub_on_order_qty = extra
        return line

    def _check_cart_is_ready_to_be_paid(self):
        super()._check_cart_is_ready_to_be_paid()
        problems = self.env["apihub.live"].order_check(self, "pago")
        if problems:
            raise ValidationError(" ".join("%s: %s" % (line.product_id.display_name, msg) for line, msg in problems))
