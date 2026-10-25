import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from . import match_rules


class ApihubProductLink(models.Model):
    _name = "apihub.product.link"
    _description = "Equivalencia producto ↔ código de proveedor"
    _order = "provider_id, state, product_tmpl_id"
    _rec_name = "provider_sku"

    product_tmpl_id = fields.Many2one("product.template", string="Producto", required=True, ondelete="cascade", index=True)
    default_code = fields.Char(related="product_tmpl_id.default_code", string="Código Interno", store=True)
    our_description_purchase = fields.Text(
        related="product_tmpl_id.description_purchase", string="Desc Compra", readonly=True)
    our_description_sale = fields.Text(
        related="product_tmpl_id.description_sale", string="Nuestra descripción de venta", readonly=True)
    brand_in_name = fields.Selection(
        [("si", "Sí"), ("no", "No")], string="¿Marca igual?", compute="_compute_checks",
        help="Sí si la marca/fábrica del proveedor aparece en el nombre de nuestro producto.")
    code_match = fields.Selection(
        [("si", "Sí"), ("desc", "Sí, en la descripción"), ("parcial", "Parcial"), ("no", "No")],
        string="¿Código igual?", compute="_compute_checks",
        help="Compara el código del proveedor con nuestra descripción de compra y de venta, sin espacios ni guiones. "
             "Sí = idéntico; Sí en la descripción = nuestro código completo aparece en la descripción del proveedor "
             "(Loma corta sus códigos a ~15 caracteres en su API); Parcial = uno contiene al otro; No = distintos.")
    provider_id = fields.Many2one("apihub.provider", string="Proveedor", required=True, ondelete="cascade", index=True)
    provider_sku = fields.Char(string="Cod Prov (API)", required=True, index=True,
                               help="El código tal como lo entrega la API del proveedor. Loma lo corta a ~15 caracteres.")
    provider_code = fields.Char(
        string="Cod Prov", compute="_compute_provider_code",
        help="Código del proveedor lo más completo posible, como se ve en su página. Si la API lo entrega cortado, se "
             "completa con el código al final de su descripción y con el prefijo de marca del ID (KIN-, ADA-...).")
    provider_ref = fields.Char(string="ID interno del proveedor")
    price_has_tax = fields.Boolean(
        string="El precio trae IVA", help="Proveedores de tienda: el precio de la página ya incluye IVA; el costo se guarda sin IVA.")
    stock_local = fields.Integer(string="Existencia local", help="Existencia en el almacén local del proveedor, del último archivo.")
    stock_national = fields.Integer(string="Existencia nacional", help="Existencia total del proveedor, del último archivo.")
    stock_at = fields.Datetime(
        string="Existencia revisada a las", help="Última vez que el robot de existencia (CT y Exel, cada hora) revisó este producto. "
        "La verificación del carrito lo trata como casi en vivo si fue hace menos de hora y media.")
    stock_date = fields.Date(string="Fecha del dato de existencia", help="Fecha del archivo del proveedor que trajo esta existencia.")
    min_price = fields.Float(string="Precio mínimo del proveedor (MXN)", digits=(12, 2),
                             help="Precio mínimo de venta que fija el proveedor (Syscom: MAP), sin IVA, en pesos.")
    provider_description = fields.Char(string="Desc Prov")
    brand = fields.Char(string="Marca Prov")
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
    cost_provider_raw = fields.Float(string="Costo Prov", digits=(12, 2),
                                     help="Lo que cobra el proveedor por SU presentación, en pesos, sin multiplicador.")
    cost_provider = fields.Float(string="Costo Prov en nuestra presentación", digits=(12, 2),
                                 help="Costo del proveedor × multiplicador: lo que costaría una unidad como la vendemos nosotros.")
    cost_reference = fields.Float(
        string="Costo Odoo", digits=(12, 2), compute="_compute_cost_reference",
        help="Lo que Odoo ya tiene como costo de este producto, en este orden: 1) la línea de este proveedor en la "
             "pestaña Compras del producto; 2) el costo (AVCO) de la ficha del producto; 3) la línea de Compras del "
             "primer proveedor del producto. Se calcula al abrir la pantalla; 0 solo si Odoo no tiene ningún costo.")
    cost_previous = fields.Float(string="Costo anterior", digits=(12, 2), help="Costo aplicado antes del último cambio (lo usa el motor).")
    cost_changed_on = fields.Date(string="Último cambio de costo")
    pending_cost = fields.Float(string="Costo en espera", digits=(12, 2),
                                help="Cambio de más de ±10 % que llegó y todavía no se aplica (el motor espera confirmación).")
    pending_on = fields.Date(string="En espera desde")
    diff_pct = fields.Float(string="% diferencia", digits=(12, 1))
    note = fields.Text(string="Notas")
    approved_by = fields.Many2one("res.users", string="Aprobado por", readonly=True)
    approved_on = fields.Datetime(string="Fecha de decisión", readonly=True)
    active = fields.Boolean(default=True)

    def _cost_odoo(self):
        self.ensure_one()
        tmpl = self.product_tmpl_id
        lines = tmpl.seller_ids.sorted(lambda l: (l.sequence, l.id))
        own = lines.filtered(lambda l: self.provider_id.partner_id and l.partner_id == self.provider_id.partner_id)
        return own[:1].price or tmpl._apihub_cost() or lines[:1].price or 0.0

    @api.depends("product_tmpl_id.standard_price", "product_tmpl_id.product_variant_ids.standard_price",
                 "product_tmpl_id.seller_ids.price",
                 "product_tmpl_id.seller_ids.partner_id", "provider_id.partner_id")
    def _compute_cost_reference(self):
        for link in self:
            link.cost_reference = link._cost_odoo()

    @api.depends("provider_sku", "provider_ref", "provider_description")
    def _compute_provider_code(self):
        """Codigo del proveedor lo mas completo posible, como se ve en su pagina, para comparar con el nuestro.
        Si la API lo entrega cortado (Loma), se completa con el codigo al final de su descripcion y con el prefijo de
        marca del ID (KIN-, ADA-, XER-). El codigo tal cual lo entrega la API esta en 'provider_sku'."""
        for link in self:
            sku = (link.provider_sku or "").strip()
            words = (link.provider_description or "").split()
            last = words[-1].strip(",;.") if words else ""
            completed = last if sku and len(last) > len(sku) and last.upper().startswith(sku.upper()) else sku
            ref = (link.provider_ref or "").strip()
            prefix = ref[:-len(sku)] if sku and len(ref) > len(sku) and ref.upper().endswith(sku.upper()) else ""
            link.provider_code = (prefix + completed) if completed else sku

    def _code_tier(self, tmpl, sku, description):
        """Que tan bien coincide un codigo de proveedor con el producto: 4 idéntico, 3 completo en la descripción del
        proveedor, 2 parcial, 1 distinto, 0 sin datos. Se compara en el idioma de referencia."""
        lang = self.env["apihub.config"].get_config().main_lang or "es_MX"
        tmpl = tmpl.with_context(lang=lang)
        sku = self._norm(sku)
        ours = {self._norm(tmpl.description_purchase), self._norm(tmpl.description_sale)}
        ours.discard("")
        if not sku or not ours:
            return 0
        if sku in ours:
            return 4
        desc = self._norm(description)
        if any(len(o) >= 6 and o in desc for o in ours):
            return 3
        if len(sku) >= 4 and any(len(o) >= 4 and (sku in o or o in sku) for o in ours):
            return 2
        return 1

    @staticmethod
    def _norm(value):
        return re.sub(r"[^A-Z0-9]", "", (value or "").upper())

    @api.depends("brand", "provider_sku", "product_tmpl_id.name", "product_tmpl_id.description_purchase",
                 "product_tmpl_id.description_sale")
    def _compute_checks(self):
        """Compara en UN idioma (Configuración → Idioma de referencia, es_MX): el nombre y las descripciones se guardan
        por idioma y el inglés suele traer copias viejas (en 1,111 productos el código de compra difiere)."""
        lang = self.env["apihub.config"].get_config().main_lang or "es_MX"
        for link in self:
            tmpl = link.product_tmpl_id.with_context(lang=lang)
            name = link._norm(tmpl.name)
            brand = link._norm(link.brand)
            link.brand_in_name = False if not brand else ("si" if brand in name else "no")
            sku = link._norm(link.provider_sku)
            ours = {link._norm(tmpl.description_purchase), link._norm(tmpl.description_sale)}
            ours.discard("")
            if not sku or not ours:
                link.code_match = False
            elif sku in ours:
                link.code_match = "si"
            elif any(len(o) >= 6 and o in link._norm(link.provider_description) for o in ours):
                link.code_match = "desc"
            elif len(sku) >= 4 and any(len(o) >= 4 and (sku in o or o in sku) for o in ours):
                link.code_match = "parcial"
            else:
                link.code_match = "no"

    _sql_constraints = [
        ("unique_link", "unique(product_tmpl_id, provider_id, provider_sku)",
         "Esa equivalencia ya existe para este producto y proveedor."),
    ]

    # ------------------------------------------------------------------ decisiones
    def _decide(self, state):
        self.write({"state": state, "approved_by": self.env.user.id, "approved_on": fields.Datetime.now()})

    def action_approve(self):
        self._decide("approved")
        self._write_vendor_code()

    def _write_vendor_code(self):
        """Escribe el codigo del proveedor en la linea de proveedor del producto (Compras), para que la orden de
        compra salga con el codigo que ese proveedor usa. Solo llena si esta vacio: si ya hay otro codigo, no lo pisa
        y lo deja anotado en la equivalencia."""
        for link in self:
            source = link.provider_id.order_code_source
            code = link.provider_ref if source == "provider_ref" else link.provider_sku if source == "provider_sku" else False
            partner = link.provider_id.partner_id
            if not code or not partner:
                continue
            lines = self.env["product.supplierinfo"].search([
                ("product_tmpl_id", "=", link.product_tmpl_id.id), ("partner_id", "=", partner.id)])
            for line in lines:
                if not line.product_code:
                    line.product_code = code
                elif line.product_code != code:
                    link.note = ((link.note or "") + "\nLa línea de Compras ya tiene el código %s; el proveedor usa %s. "
                                 "No se cambió." % (line.product_code, code)).strip()

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
        lang = self.env["apihub.config"].get_config().main_lang or "es_MX"
        counts = {"created": 0, "updated": 0, "kept": 0, "no_product": 0, "discarded": 0, "no_cuadra": 0}
        # Varios candidatos del mismo proveedor para un mismo producto (ej. SSD de 240/480/960 GB que comparten el
        # principio del codigo): si uno coincide claramente mejor (parcial o mejor), los demas no se ofrecen.
        best = {}
        for row in rows:
            tmpl = templates.get(row.get("default_code"))
            if tmpl:
                tier = self._code_tier(tmpl, row.get("provider_sku"), row.get("provider_description"))
                row["_tier"] = tier
                best[tmpl.id] = max(best.get(tmpl.id, 0), tier)
        kept_rows = []
        for row in rows:
            tmpl = templates.get(row.get("default_code"))
            if tmpl and best.get(tmpl.id, 0) >= 2 and row.get("_tier", 0) < best[tmpl.id]:
                counts["discarded"] += 1
                continue
            kept_rows.append(row)
        for row in kept_rows:
            tmpl = templates.get(row.get("default_code"))
            sku = (row.get("provider_sku") or "").strip()
            if not tmpl or not sku:
                counts["no_product"] += 1
                continue
            res = match_rules.evaluate(
                tmpl.with_context(lang=lang).name,
                [tmpl.with_context(lang=lang).description_sale, tmpl.with_context(lang=lang).description_ecommerce],
                [tmpl.with_context(lang=lang).description_purchase, tmpl.with_context(lang=lang).description_sale],
                row.get("provider_sku"), row.get("provider_sku"), row.get("provider_description"), row.get("brand"),
                row.get("cost_reference") or tmpl._apihub_cost(), row.get("cost_provider_raw"), row.get("multiplier") or 1.0,
                tmpl.is_published)
            if res["failed"]:
                # si una regla de marca, descripción, código o precio no cuadra no es el mismo producto: no se sugiere
                counts["no_cuadra"] += 1
                continue
            state = "review"  # nada se da por seguro: lo aprueba una persona
            review_reason = row.get("review_reason")
            if abs((row.get("multiplier") or 1.0) - 1.0) > 1e-9:
                review_reason = "multiplicador distinto de 1 sin confirmar: verificar la presentacion (pieza/paquete) antes de aprobar"
            vals = {
                "provider_ref": row.get("provider_ref"), "provider_description": row.get("provider_description"),
                "brand": row.get("brand"), "multiplier": row.get("multiplier") or 1.0,
                "match_reason": row.get("match_reason"), "review_reason": review_reason,
                "confidence": row.get("confidence") or False, "cost_provider": row.get("cost_provider") or 0.0,
                "cost_provider_raw": row.get("cost_provider_raw") or 0.0,
                "diff_pct": row.get("diff_pct") or 0.0,
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
    def remove_unmatched_suppliers(self, provider_code, catalog_size, dry_run=True, min_catalog=100):
        """Regla de Javier (2026-10-18): si un producto tiene a este proveedor en Compras y, tras el cruce y la ultima
        opcion (buscar nuestra descripcion de compra en su catalogo), el proveedor no lo tiene, se quita el proveedor
        de ese producto. Sin proveedor no queda el producto: si es el unico, se avisa y no se quita.

        Solo 'dry_run=False' borra. Devuelve las lineas, con precio y codigo, para guardarlas como respaldo.
        catalog_size: cuantos productos trajo la corrida del proveedor; si es muy poco (la API fallo) no se hace nada."""
        provider = self.env["apihub.provider"].search([("code", "=", provider_code)], limit=1)
        if not provider or not provider.partner_id:
            raise UserError(_("El proveedor %s no esta ligado a un proveedor de Odoo.", provider_code))
        if catalog_size < min_catalog:
            raise UserError(_("La corrida de %(p)s trajo solo %(n)s productos: no se quita ningun proveedor.",
                              p=provider.name, n=catalog_size))
        matched = self.with_context(active_test=False).search(
            [("provider_id", "=", provider.id), ("state", "!=", "rejected")]).mapped("product_tmpl_id")
        lines = self.env["product.supplierinfo"].with_context(active_test=False).search(
            [("partner_id", "=", provider.partner_id.id), ("product_tmpl_id", "not in", matched.ids)])
        removed, kept = [], []
        for line in lines:
            info = {"default_code": line.product_tmpl_id.default_code, "line_id": line.id, "price": line.price,
                    "sequence": line.sequence, "product_code": line.product_code}
            if len(line.product_tmpl_id.seller_ids) <= 1:
                kept.append(dict(info, reason="es su unico proveedor"))
            else:
                removed.append(info)
        if not dry_run:
            self.env["product.supplierinfo"].browse([r["line_id"] for r in removed]).unlink()
        return {"dry_run": dry_run, "removed": removed, "kept": kept}

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
