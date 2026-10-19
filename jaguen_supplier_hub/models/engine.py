import logging
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
    below_min = fields.Integer(string="Bajo el precio mínimo del proveedor")
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
    def run_costs(self, provider_code, records, dry_run=None):
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
        for link in links:
            rec = by_ref.get(norm_code(link.provider_ref)) or by_sku.get(norm_code(link.provider_sku))
            if not rec:
                counts["not_in_feed"] += 1
                continue
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
            if rec.get("map_usd"):
                minimum = rec["map_usd"] * (rec.get("exchange_rate") or 1.0) if (rec.get("currency") or "").upper() == "USD" else rec["map_usd"]
                mins[tmpl.id] = (tmpl, max(minimum, mins.get(tmpl.id, (None, 0.0))[1]), link.default_code)
        if not dry:
            counts["reordered"], counts["avco"], counts["rules"] = self._after_costs(touched)
            counts["below_min"] = self._check_min_price(mins, notes)
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
    def _check_min_price(self, mins, notes):
        """Cuantos productos quedarian con el precio público por debajo del mínimo del proveedor. Solo avisa en el detalle de
        la corrida: no cambia precios ni publica. Si el producto aún no tiene regla en la lista pública, calcula el precio
        que tendría con la regla más común (así se ve antes de publicarlo)."""
        pricelist = self.env["apihub.config"].get_config().public_pricelist_id
        if not mins:
            return 0
        if not pricelist:
            notes.append("No hay lista de precio público en Configuración: no se revisó el precio mínimo del proveedor.")
            return 0
        params = self._rule_params(pricelist)
        below = 0
        for tmpl, minimum, code in mins.values():
            has_rule = self.env["product.pricelist.item"].search_count([("pricelist_id", "=", pricelist.id), ("product_tmpl_id", "=", tmpl.id)])
            try:
                if has_rule:
                    price = pricelist._get_product_price(tmpl.product_variant_id, 1.0)
                elif params:
                    price = tmpl.standard_price * (1 - params[0] / 100.0)
                    if params[1]:
                        price = round(price / params[1]) * params[1]
                else:
                    continue
            except Exception as exc:  # noqa: BLE001
                notes.append("%s: no se pudo calcular el precio público (%s)" % (code, exc))
                continue
            if price + 0.005 < minimum:
                below += 1
                notes.append("%s: precio público %.2f por debajo del mínimo %.2f%s" % (
                    code, price, minimum, "" if has_rule else " (si se publica con la regla más común)"))
        return below

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
