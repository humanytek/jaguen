from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ApihubProductLink(models.Model):
    _name = "apihub.product.link"
    _description = "Equivalencia producto ↔ código de proveedor"
    _order = "provider_id, state, product_tmpl_id"
    _rec_name = "provider_sku"

    product_tmpl_id = fields.Many2one("product.template", string="Producto", required=True, ondelete="cascade", index=True)
    default_code = fields.Char(related="product_tmpl_id.default_code", string="Cód. interno", store=True)
    our_description_purchase = fields.Text(
        related="product_tmpl_id.description_purchase", string="Nuestra descripción de compra", readonly=True)
    our_description_sale = fields.Text(
        related="product_tmpl_id.description_sale", string="Nuestra descripción de venta", readonly=True)
    provider_id = fields.Many2one("apihub.provider", string="Proveedor", required=True, ondelete="cascade", index=True)
    provider_sku = fields.Char(string="Código del proveedor", required=True, index=True)
    provider_ref = fields.Char(string="ID interno del proveedor")
    provider_description = fields.Char(string="Descripción del proveedor")
    brand = fields.Char(string="Marca")
    multiplier = fields.Float(
        string="Multiplicador", digits=(12, 4), default=1.0,
        help="Costo por unidad de Odoo = costo del proveedor × multiplicador. 1 si ambos venden la misma presentación; "
             "5 si el proveedor vende por pieza y en Odoo el producto es una caja de 5.",
    )
    state = fields.Selection(
        [("auto", "Coincidencia segura"), ("review", "Por revisar"), ("approved", "Aprobado"), ("rejected", "Rechazado")],
        string="Estado", default="review", required=True, index=True,
    )
    match_reason = fields.Char(string="Cómo coincidió")
    review_reason = fields.Char(string="Por qué se pide revisar")
    confidence = fields.Selection([("alta", "Alta"), ("media", "Media"), ("baja", "Baja")], string="Confianza del costo")
    cost_provider_raw = fields.Float(string="Costo del proveedor (tal cual)", digits=(12, 2),
                                     help="Lo que cobra el proveedor por SU presentación, en pesos, sin multiplicador.")
    cost_provider = fields.Float(string="Costo en nuestra presentación", digits=(12, 2),
                                 help="Costo del proveedor × multiplicador: lo que costaría una unidad como la vendemos nosotros.")
    cost_reference = fields.Float(string="Costo de referencia en Odoo", digits=(12, 2))
    diff_pct = fields.Float(string="% diferencia", digits=(12, 1))
    note = fields.Text(string="Notas")
    approved_by = fields.Many2one("res.users", string="Aprobado por", readonly=True)
    approved_on = fields.Datetime(string="Fecha de decisión", readonly=True)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("unique_link", "unique(product_tmpl_id, provider_id, provider_sku)",
         "Esa equivalencia ya existe para este producto y proveedor."),
    ]

    # ------------------------------------------------------------------ decisiones
    def _decide(self, state):
        self.write({"state": state, "approved_by": self.env.user.id, "approved_on": fields.Datetime.now()})

    def action_approve(self):
        self._decide("approved")

    def action_reject(self):
        self._decide("rejected")

    def action_reopen(self):
        self.write({"state": "review", "approved_by": False, "approved_on": False})

    # ------------------------------------------------------------------ carga desde el cruce
    @api.model
    def upsert_from_rows(self, provider_code, rows):
        """Carga el resultado del cruce (tools/match_exel.py). Sin tocar lo que ya decidió una persona.

        rows: lista de diccionarios con default_code, provider_sku y, opcionalmente, provider_ref,
        provider_description, brand, multiplier, state ('auto' o 'review'), match_reason, review_reason,
        confidence, cost_provider, cost_reference, diff_pct, note.
        """
        provider = self.env["apihub.provider"].search([("code", "=", provider_code)], limit=1)
        if not provider:
            raise UserError(_("No existe el proveedor %s.", provider_code))
        templates = {}
        codes = {r["default_code"] for r in rows if r.get("default_code")}
        for tmpl in self.env["product.template"].with_context(active_test=False).search([("default_code", "in", list(codes))]):
            templates.setdefault(tmpl.default_code, tmpl)
        counts = {"created": 0, "updated": 0, "kept": 0, "no_product": 0}
        for row in rows:
            tmpl = templates.get(row.get("default_code"))
            sku = (row.get("provider_sku") or "").strip()
            if not tmpl or not sku:
                counts["no_product"] += 1
                continue
            state = row.get("state") or "review"
            review_reason = row.get("review_reason")
            if state == "auto" and abs((row.get("multiplier") or 1.0) - 1.0) > 1e-9:
                # un multiplicador distinto de 1 nunca se da por seguro: lo confirma una persona
                state = "review"
                review_reason = "multiplicador distinto de 1 sin confirmar: verificar la presentacion (pieza/paquete) antes de aprobar"
            vals = {
                "provider_ref": row.get("provider_ref"), "provider_description": row.get("provider_description"),
                "brand": row.get("brand"), "multiplier": row.get("multiplier") or 1.0,
                "match_reason": row.get("match_reason"), "review_reason": review_reason,
                "confidence": row.get("confidence") or False, "cost_provider": row.get("cost_provider") or 0.0,
                "cost_provider_raw": row.get("cost_provider_raw") or 0.0,
                "cost_reference": row.get("cost_reference") or 0.0, "diff_pct": row.get("diff_pct") or 0.0,
            }
            link = self.with_context(active_test=False).search(
                [("product_tmpl_id", "=", tmpl.id), ("provider_id", "=", provider.id), ("provider_sku", "=", sku)], limit=1)
            if link:
                if link.state in ("approved", "rejected"):
                    counts["kept"] += 1
                else:
                    link.write(dict(vals, state=state))
                    counts["updated"] += 1
            else:
                self.create(dict(vals, product_tmpl_id=tmpl.id, provider_id=provider.id, provider_sku=sku,
                                 state=state))
                counts["created"] += 1
        return counts

    @api.model
    def export_decisions(self):
        """Decisiones tomadas por una persona (para guardarlas fuera de Odoo; staging se reconstruye en cada subida)."""
        links = self.with_context(active_test=False).search([("state", "in", ("approved", "rejected"))])
        return [{
            "default_code": link.default_code, "provider": link.provider_id.code, "provider_sku": link.provider_sku,
            "state": link.state, "multiplier": link.multiplier, "note": link.note,
        } for link in links]

    @api.model
    def import_decisions(self, rows):
        done = 0
        for row in rows:
            link = self.with_context(active_test=False).search([
                ("default_code", "=", row["default_code"]), ("provider_id.code", "=", row["provider"]),
                ("provider_sku", "=", row["provider_sku"])], limit=1)
            if link:
                link.write({"state": row["state"], "multiplier": row.get("multiplier") or link.multiplier,
                            "note": row.get("note"), "approved_by": self.env.user.id,
                            "approved_on": fields.Datetime.now()})
                done += 1
        return done
