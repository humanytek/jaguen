import logging
import math
from collections import Counter

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .match_rules import norm_code

_logger = logging.getLogger(__name__)


class ApihubRunLog(models.Model):
    _name = "apihub.run.log"
    _description = "Registro de una corrida del motor"
    _order = "run_date desc, id desc"

    provider_id = fields.Many2one("apihub.provider", string="Proveedor", required=True, ondelete="cascade")
    run_date = fields.Datetime(string="Fecha", default=fields.Datetime.now)
    dry_run = fields.Boolean(string="Simulación")
    approved_links = fields.Integer(string="Equivalencias aprobadas")
    cost_updated = fields.Integer(string="Costos actualizados")
    cost_same = fields.Integer(string="Costos sin cambio")
    lines_created = fields.Integer(string="Líneas de proveedor creadas")
    sanity_skipped = fields.Integer(string="En espera por cambio grande")
    not_in_feed = fields.Integer(string="No vienen en el archivo")
    reordered = fields.Integer(string="Productos reordenados")
    avco_updated = fields.Integer(string="AVCO actualizados")
    rules_created = fields.Integer(string="Reglas de precio creadas")
    below_min = fields.Integer(string="Precios subidos al mínimo del proveedor")
    notes = fields.Text(string="Detalle")


class ApihubPublishLog(models.Model):
    _name = "apihub.publish.log"
    _description = "Registro de una corrida de publicación"
    _order = "run_date desc, id desc"

    run_date = fields.Datetime(string="Fecha", default=fields.Datetime.now)
    dry_run = fields.Boolean(string="Simulación")
    managed = fields.Integer(string="Productos que maneja")
    n_local = fields.Integer(string="Entrega rápida")
    n_on_order = fields.Integer(string="Sobre pedido")
    n_out = fields.Integer(string="Agotados")
    published = fields.Integer(string="Publicados")
    unpublished = fields.Integer(string="Despublicados")
    rules_created = fields.Integer(string="Reglas de precio creadas")
    prices_raised = fields.Integer(string="Precios subidos al mínimo")
    notes = fields.Text(string="Detalle")


class ApihubEngine(models.AbstractModel):
    """Motor diario: costo del proveedor -> Compras -> orden de proveedores -> AVCO -> reglas de precio de venta.

    El costo sale SIEMPRE del archivo o la API del proveedor (nunca de lo que ya hay en Compras). docs/DECISIONES.md 7z."""
    _name = "apihub.engine"
    _description = "Motor de costos y precios"

    # ------------------------------------------------------------------ costo
    @api.model
    def _cost_mxn(self, provider, rec):
        """Costo en pesos de un registro del archivo del proveedor, con la regla de tipo de cambio de cada proveedor."""
        cost = rec.get("cost")
        if rec.get("cost_usd") not in (None, 0, 0.0):
            return provider.to_mxn(rec["cost_usd"], "USD", provider_rate=rec.get("exchange_rate"))
        currency = (rec.get("currency") or "MXN").upper()
        if currency == "USD" and rec.get("exchange_rate"):
            return cost   # CT ya trae el costo convertido con su tipo de cambio y su promoción
        if currency == "USD":
            return provider.to_mxn(cost, "USD", provider_rate=rec.get("exchange_rate"))
        return cost

    @api.model
    def _special_costs(self, provider):
        """Precios especiales cargados aparte (ej. Nextep en Exel): clave -> costo."""
        rows = self.env["apihub.special.price"].search([("provider_id", "=", provider.id)])
        return {norm_code(r.provider_sku): r.cost for r in rows}

    # ------------------------------------------------------------------ cambios grandes
    @api.model
    def _recent_move(self, link, today):
        """Cuanto se movio (o esta en espera de moverse) el costo de otro proveedor del mismo producto, o None."""
        days = lambda d: (today - d).days if d else 99
        if link.pending_cost and link.cost_provider and days(link.pending_on) <= 1:
            return link.pending_cost / link.cost_provider - 1
        if link.cost_previous and link.cost_provider and days(link.cost_changed_on) <= 2:
            return link.cost_provider / link.cost_previous - 1
        return None

    @api.model
    def _decide(self, link, cost, cfg, dry):
        """'apply' o 'hold'. Un cambio de mas de +-10 % de un dia a otro solo se aplica si los demas proveedores del
        producto se movieron igual (+-3 puntos) o si el mismo precio llega otra vez al dia siguiente."""
        base = link.cost_provider
        if not base:
            return "apply"
        change = cost / base - 1
        if abs(change) <= cfg.daily_change_pct / 100.0:
            return "apply"
        today = fields.Date.context_today(self)
        if link.pending_cost and link.pending_on and link.pending_on < today and abs(cost / link.pending_cost - 1) <= 0.005:
            return "apply"
        others = self.env["apihub.product.link"].search([
            ("product_tmpl_id", "=", link.product_tmpl_id.id), ("provider_id", "!=", link.provider_id.id), ("state", "=", "approved")])
        tol = cfg.peer_tolerance_pct / 100.0
        for other in others:
            move = self._recent_move(other, today)
            if move is not None and move * change > 0 and abs(move - change) <= tol:
                return "apply"
        if not dry and not (link.pending_cost and abs(cost / link.pending_cost - 1) <= 0.005 and link.pending_on == today):
            link.write({"pending_cost": cost, "pending_on": today})
        return "hold"

    # ------------------------------------------------------------------ corrida
    @api.model
    def run_costs(self, provider_code, records, dry_run=None, data_date=None):
        """Aplica el archivo de un proveedor. records: lista normalizada de los robots (sku, provider_id, cost, currency...).

        Devuelve las cuentas de la corrida. Con dry_run solo cuenta, no escribe."""
        cfg = self.env["apihub.config"].get_config()
        dry = cfg.dry_run if dry_run is None else dry_run
        provider = self.env["apihub.provider"].search([("code", "=", provider_code)], limit=1)
        if not provider or not provider.partner_id:
            raise UserError(_("El proveedor %s no está ligado a un proveedor de Odoo.", provider_code))
        if len(records) < 100:
            raise UserError(_("El archivo de %(p)s trae solo %(n)s productos: no se aplica nada.", p=provider.name, n=len(records)))
        by_sku = {norm_code(r.get("sku")): r for r in records if r.get("sku")}
        by_ref = {norm_code(r.get("provider_id")): r for r in records if r.get("provider_id")}
        special = self._special_costs(provider)
        links = self.env["apihub.product.link"].search([("provider_id", "=", provider.id), ("state", "=", "approved")])
        counts, touched, notes = Counter(), self.env["product.template"], []
        mins = {}   # producto -> (producto, precio minimo en pesos): solo proveedores que publican un minimo (Syscom MAP)
        stock_date = fields.Date.to_date(data_date) if data_date else fields.Date.context_today(self)
        for link in links:
            rec = by_ref.get(norm_code(link.provider_ref)) or by_sku.get(norm_code(link.provider_sku))
            if not rec:
                counts["not_in_feed"] += 1
                continue
            minimum = 0.0
            if rec.get("map_usd"):
                minimum = rec["map_usd"] * (rec.get("exchange_rate") or 1.0) if (rec.get("currency") or "").upper() == "USD" else rec["map_usd"]
            if not dry:
                link.write({"stock_local": int(rec.get("stock_hermosillo") or 0), "stock_national": int(rec.get("stock_national") or 0),
                            "stock_date": stock_date, "min_price": round(minimum, 2)})
            raw = special.get(norm_code(rec.get("sku"))) or (self._cost_mxn(provider, rec) or 0.0) * (provider.cost_factor or 1.0)
            cost = round((raw or 0.0) * (link.multiplier or 1.0), 2)
            if cost <= 0:
                counts["not_in_feed"] += 1
                continue
            decision = self._decide(link, cost, cfg, dry)
            if decision == "hold":
                counts["held"] += 1
                notes.append("%s: costo %.2f en espera (anterior %.2f)" % (link.default_code, cost, link.cost_provider))
                continue
            tmpl = link.product_tmpl_id
            line = tmpl.seller_ids.filtered(lambda s: s.partner_id == provider.partner_id)[:1]
            if line:
                if abs(line.price - cost) > 0.005:
                    counts["updated"] += 1
                    if not dry:
                        line.price = cost
                else:
                    counts["same"] += 1
            else:
                counts["created"] += 1
                if not dry:
                    self.env["product.supplierinfo"].create({
                        "partner_id": provider.partner_id.id, "product_tmpl_id": tmpl.id, "price": cost, "min_qty": 0.0,
                        "sequence": 99, "delay": 1,
                    })
            code = {"provider_ref": link.provider_ref, "provider_sku": link.provider_sku}.get(provider.order_code_source)
            if code and not dry:
                line = tmpl.seller_ids.filtered(lambda s: s.partner_id == provider.partner_id)[:1]
                if line and not line.product_code:
                    line.product_code = code
            if not dry:
                if abs((link.cost_provider or 0.0) - cost) > 0.005:
                    link.write({"cost_previous": link.cost_provider, "cost_changed_on": fields.Date.context_today(self)})
                link.write({"cost_provider": cost, "pending_cost": 0.0, "pending_on": False})
            touched |= tmpl
            if minimum:
                mins[tmpl.id] = (tmpl, max(minimum, mins.get(tmpl.id, (None, 0.0))[1]), link.default_code)
        if not dry:
            counts["reordered"], counts["avco"], counts["rules"] = self._after_costs(touched)
            counts["below_min"] = sum(self._apply_min_price(t, m, notes, c) for t, m, c in mins.values())
        log = self.env["apihub.run.log"].create({
            "provider_id": provider.id, "dry_run": dry, "approved_links": len(links), "cost_updated": counts["updated"],
            "cost_same": counts["same"], "lines_created": counts["created"], "sanity_skipped": counts["held"],
            "not_in_feed": counts["not_in_feed"], "reordered": counts["reordered"], "avco_updated": counts["avco"],
            "rules_created": counts["rules"], "below_min": counts["below_min"], "notes": "\n".join(notes[:200]) or False,
        })
        _logger.info("ApiHub %s: %s", provider.code, dict(counts))
        return dict(counts, log_id=log.id, dry_run=dry)

    # ------------------------------------------------------------------ precio minimo del proveedor
    @api.model
    def _rule_params(self, pricelist):
        """Descuento y redondeo que mas se repiten en las reglas de fórmula de la lista (los mismos que usa _ensure_rules)."""
        existing = self.env["product.pricelist.item"].search([
            ("pricelist_id", "=", pricelist.id), ("applied_on", "=", "1_product"),
            ("compute_price", "=", "formula"), ("base", "=", "standard_price")], limit=400)
        if not existing:
            return None
        return Counter((r.price_discount, r.price_round) for r in existing).most_common(1)[0][0]

    @api.model
    def _apply_min_price(self, tmpl, minimum, notes, code):
        """Sube el precio de la lista pública de un producto si quedaría por debajo del mínimo del proveedor (Syscom MAP).
        Ajusta solo el porcentaje de la regla de esa lista (sigue la fórmula sobre el costo, redondeo hacia arriba) y lo
        regresa al normal cuando el normal ya cumple. Devuelve 1 si cambió la regla. No avisa: queda en el detalle."""
        pricelist = self.env["apihub.config"].get_config().public_pricelist_id
        if not pricelist or not minimum or minimum <= 0:
            return 0
        item = self.env["product.pricelist.item"].search([
            ("pricelist_id", "=", pricelist.id), ("product_tmpl_id", "=", tmpl.id), ("applied_on", "=", "1_product"),
            ("compute_price", "=", "formula"), ("base", "=", "standard_price")], limit=1)
        params = self._rule_params(pricelist)
        cost = tmpl.standard_price
        if not item or not params or cost <= 0:
            return 0
        rnd = item.price_round or params[1] or 0.0

        def price_for(discount):
            price = cost * (1 - discount / 100.0)
            return round(price / rnd) * rnd if rnd else price

        if price_for(params[0]) + 0.005 >= minimum:
            target = params[0]
        else:
            floor_price = math.ceil(minimum / rnd - 1e-9) * rnd if rnd else minimum
            target = -math.ceil((floor_price / cost - 1) * 10000 - 1e-9) / 100.0
        if abs(item.price_discount - target) <= 0.005:
            return 0
        item.write({"price_discount": target, "price_markup": -target})
        notes.append("%s: regla de la lista pública ajustada a %.2f %% (mínimo del proveedor %.2f, precio %.2f)" % (
            code, -target, minimum, price_for(target)))
        return 1

    # ------------------------------------------------------------------ publicacion
    @api.model
    def run_publication(self, dry_run=None):
        """Decide la disponibilidad y la publicación de los productos que maneja el motor (todos sus proveedores son de los 5).

        Entrega rápida (alguna regla de almacén local cumple el mínimo), Sobre pedido (algún proveedor lo tiene en cualquier
        almacén) o Agotado. Publica lo que tiene existencia; lo agotado sigue visible y se despublica tras los días
        configurados seguidos. Un proveedor sin dato fresco no cuenta y no hace avanzar ni despublica. Docs 2, 7c, 7j."""
        cfg = self.env["apihub.config"].get_config()
        dry = cfg.dry_run if dry_run is None else dry_run
        today = fields.Date.context_today(self)
        providers = self.env["apihub.provider"].search([])
        group_of = {p.partner_id.id: p for p in providers if p.partner_id}
        Link = self.env["apihub.product.link"]
        links = Link.search([("state", "=", "approved"), ("provider_id", "in", providers.ids)])
        last = {}
        for link in links:
            if link.stock_date and (link.provider_id.id not in last or link.stock_date > last[link.provider_id.id]):
                last[link.provider_id.id] = link.stock_date
        stale = {p.id for p in providers if p.id not in last or (today - last[p.id]).days > math.ceil((p.max_data_age_hours or 24) / 24.0)}
        rules = self.env["apihub.warehouse.rule"].search([("active", "=", True), ("counts_for_publication", "=", True)])
        rules_of = {}
        for r in rules:
            rules_of.setdefault(r.provider_id.id, []).append(r)
        by_tmpl = {}
        for link in links:
            by_tmpl.setdefault(link.product_tmpl_id.id, []).append(link.id)
        counts, notes = Counter(), []
        publish, unpublish, state_changes = [], [], []
        for tmpl_id, link_ids in by_tmpl.items():
            tlinks = Link.browse(link_ids)
            tmpl = tlinks[0].product_tmpl_id
            lines = tmpl.seller_ids.filtered(lambda s: s.partner_id)
            if not tmpl.active or not tmpl.sale_ok or not lines or not all(s.partner_id.id in group_of for s in lines):
                continue
            counts["managed"] += 1
            local = national = any_stale = False
            for link in tlinks:
                p = link.provider_id
                if p.id in stale:
                    any_stale = True
                    continue
                if link.stock_date != last.get(p.id):
                    continue   # no vino en el ultimo archivo: no tiene existencia
                prules = rules_of.get(p.id, [])
                threshold = (prules[0].min_stock_override if prules and prules[0].min_stock_override > 0 else p.min_stock) or 1
                star = any(r.code == "*" for r in prules)
                if prules and (link.stock_national if star else link.stock_local) >= threshold:
                    local = True
                if link.stock_national >= (p.min_stock or 1):
                    national = True
            state = "local" if local else "on_order" if national else "out"
            counts["n_" + state] += 1
            if any_stale and state == "out":
                continue   # sin dato confiable de algun proveedor: no se toca nada de lo agotado
            state_changes.append((tmpl, state))
            if state == "out":
                if tmpl.apihub_out_since and tmpl.is_published and (today - tmpl.apihub_out_since).days >= cfg.unpublish_days:
                    unpublish.append(tmpl)
            elif not tmpl.is_published:
                if tmpl.image_1920:
                    publish.append(tmpl)
                else:
                    notes.append("%s: tiene existencia pero no tiene foto, no se publica" % tmpl.default_code)
        limit = max(5, int(counts["managed"] * (cfg.max_unpublish_pct or 0) / 100.0))
        if len(unpublish) > limit:
            notes.append("Freno: iba a despublicar %d productos (máximo %d). No se despublicó ninguno." % (len(unpublish), limit))
            unpublish = []
        if not dry:
            for tmpl, state in state_changes:
                vals = {}
                if tmpl.apihub_state != state:
                    vals["apihub_state"] = state
                if state == "out" and not tmpl.apihub_out_since:
                    vals["apihub_out_since"] = today
                elif state != "out" and tmpl.apihub_out_since:
                    vals["apihub_out_since"] = False
                if vals:
                    tmpl.write(vals)
            for tmpl in publish:
                tmpl.write({"is_published": True})
            for tmpl in unpublish:
                tmpl.write({"is_published": False})
            raised = 0
            for tmpl in publish:
                first = tmpl.seller_ids.filtered(lambda s: s.partner_id).sorted(lambda s: (s.sequence, s.id))[0]
                provider = group_of.get(first.partner_id.id)
                if provider:
                    counts["rules"] += self._ensure_rules(tmpl, provider)
                minimum = max(Link.browse(by_tmpl[tmpl.id]).mapped("min_price") or [0.0])
                if minimum:
                    raised += self._apply_min_price(tmpl, minimum, notes, tmpl.default_code)
            counts["raised"] = raised
        counts["published"], counts["unpublished"] = len(publish), len(unpublish)
        for tmpl in publish:
            notes.append("%s: se %s (%s)" % (tmpl.default_code, "publicaría" if dry else "publicó", tmpl.apihub_state or "-"))
        for tmpl in unpublish:
            notes.append("%s: se %s tras %s días agotado" % (tmpl.default_code, "despublicaría" if dry else "despublicó", cfg.unpublish_days))
        log = self.env["apihub.publish.log"].create({
            "dry_run": dry, "managed": counts["managed"], "n_local": counts["n_local"], "n_on_order": counts["n_on_order"],
            "n_out": counts["n_out"], "published": counts["published"], "unpublished": counts["unpublished"],
            "rules_created": counts["rules"], "prices_raised": counts["raised"], "notes": "\n".join(notes[:300]) or False,
        })
        stale_names = [p.code for p in providers if p.id in stale]
        return dict(counts, log_id=log.id, dry_run=dry, proveedores_sin_dato_fresco=stale_names)

    # ------------------------------------------------------------------ despues de los costos
    @api.model
    def _after_costs(self, templates):
        """Orden de proveedores, AVCO (solo sin existencia) y reglas de precio que falten."""
        providers = self.env["apihub.provider"].search([])
        group_of = {p.partner_id.id: p for p in providers if p.partner_id}
        reordered = avco = rules = 0
        for tmpl in templates:
            lines = tmpl.seller_ids.filtered(lambda s: s.partner_id)
            if not lines:
                continue
            # Proveedor 1 = el mas barato, solo cuando TODOS los proveedores del producto son de los 5 (los demas, como
            # Amazon o compras directas, no tienen archivo y no se reordenan solos).
            if all(s.partner_id.id in group_of for s in lines):
                ordered = lines.sorted(lambda s: (s.price, s.id))
                if [s.id for s in ordered] != [s.id for s in lines.sorted(lambda s: (s.sequence, s.id))]:
                    reordered += 1
                for pos, s in enumerate(ordered, start=1):
                    if s.sequence != pos:
                        s.sequence = pos
            first = lines.sorted(lambda s: (s.sequence, s.id))[0]
            provider = group_of.get(first.partner_id.id)
            if not provider:
                continue
            if tmpl.qty_available == 0:
                new = round(first.price * (provider.avco_factor or 1.0), 2)
                if new > 0 and abs(tmpl.standard_price - new) > 0.005:
                    tmpl.sudo().standard_price = new
                    avco += 1
            rules += self._ensure_rules(tmpl, provider)
        return reordered, avco, rules

    @api.model
    def _ensure_rules(self, tmpl, provider):
        """Crea la regla de precio de venta que falte (solo grupo Distribuidor y producto publicado). Los porcentajes se
        copian de las reglas que ya existen en cada lista: no viven en el código."""
        if provider.pricing_group != "distribuidor" or not tmpl.is_published:
            return 0
        lists = self.env["apihub.config"].get_config().sale_pricelist_ids
        item = self.env["product.pricelist.item"]
        made = 0
        for pl in lists:
            if item.search_count([("pricelist_id", "=", pl.id), ("product_tmpl_id", "=", tmpl.id)]):
                continue
            existing = item.search([("pricelist_id", "=", pl.id), ("applied_on", "=", "1_product"),
                                    ("compute_price", "=", "formula"), ("base", "=", "standard_price")], limit=400)
            if not existing:
                continue
            best = Counter((r.price_markup, r.price_discount, r.price_round) for r in existing).most_common(1)[0][0]
            item.create({
                "pricelist_id": pl.id, "applied_on": "1_product", "product_tmpl_id": tmpl.id, "compute_price": "formula",
                "base": "standard_price", "price_markup": best[0], "price_discount": best[1], "price_round": best[2],
            })
            made += 1
        return made
