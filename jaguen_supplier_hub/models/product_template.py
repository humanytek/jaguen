from odoo import _, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    apihub_state = fields.Selection(
        [("local", "Entrega rápida"), ("on_order", "Sobre pedido"), ("out", "Agotado")],
        string="Disponibilidad (ApiHub)", copy=False,
        help="La calcula la corrida de publicación con la existencia de los proveedores.")
    apihub_out_since = fields.Date(
        string="Agotado desde (ApiHub)", copy=False,
        help="Primer día de la racha de días en que ningún proveedor lo tiene. A los días configurados se despublica.")

    apihub_no_publish = fields.Boolean(
        string="No publicar solo (ApiHub)", copy=False,
        help="ApiHub sigue actualizando costo, proveedor y AVCO de este producto, pero nunca lo publica por su cuenta "
             "(ej. papel bond: solo se publican las cajas de 5,000 hojas, las demás presentaciones no).")

    apihub_exact_margin = fields.Boolean(
        string="Precio por margen exacto (ApiHub)", copy=False,
        help="Las 4 listas (Página, Clientes, Grandes, Competencia) toman el margen del nombre de la lista: precio = costo ÷ (1 − margen). "
             "ApiHub crea y mantiene estas reglas de precio sobre el costo (AVCO), aunque el producto no esté publicado.")
    apihub_price_round = fields.Float(
        string="Redondeo del precio (ApiHub)", copy=False, default=0.0, digits=(12, 2),
        help="Solo con margen exacto: redondeo de las reglas (ej. 5 para cajas de papel). 0 = 0.25.")

    apihub_show_variant_code = fields.Boolean(
        string="Mostrar la clave de la variante en la tienda", copy=False,
        help="En la ficha de la tienda se muestra, debajo del título, solo la clave (referencia interna) de la variante elegida. "
             "Para productos con variantes cuya clave es la del proveedor (ej. Sablon).")

    def _get_additionnal_combination_info(self, product_or_template, quantity, date, website):
        info = super()._get_additionnal_combination_info(product_or_template, quantity, date, website)
        if self.apihub_show_variant_code:
            info["apihub_clave"] = product_or_template.default_code if product_or_template._name == "product.product" else ""
        return info

    def write(self, vals):
        before = {tmpl.id: tmpl.is_published for tmpl in self} if "is_published" in vals else {}
        res = super().write(vals)
        if before:
            self._apihub_sync_redirects(before)
        return res

    def _apihub_sync_redirects(self, before):
        """Al despublicar un producto (ApiHub o a mano) su página deja de dar 404: se redirige a la página de inicio (302, porque
        el producto puede volver). Al publicarlo otra vez se borra la redirección (Javier, 2026-10-20)."""
        Rewrite = self.env["website.rewrite"].sudo().with_context(active_test=False)
        for tmpl in self.sudo():
            if before.get(tmpl.id) is None or before[tmpl.id] == tmpl.is_published:
                continue
            url = tmpl.website_url
            if not url or not url.startswith("/shop/"):
                continue
            mine = Rewrite.search([("url_from", "=", url), ("name", "=like", "ApiHub:%")])
            if tmpl.is_published:
                mine.unlink()
            elif not mine:
                Rewrite.create({
                    "name": "ApiHub: %s despublicado" % (tmpl.default_code or tmpl.id), "url_from": url, "url_to": "/",
                    "redirect_type": "302", "website_id": tmpl.website_id.id or False})

    def _apihub_cost(self):
        """Costo (standard_price) del producto. Con variantes Odoo deja el del producto en 0: se lee de la primera variante."""
        self.ensure_one()
        if len(self.product_variant_ids) <= 1:
            return self.standard_price
        return self.product_variant_ids[0].standard_price

    def _apihub_set_cost(self, value):
        """Escribe el costo; con variantes lo pone igual en todas (en un producto ApiHub todas cuestan lo mismo)."""
        self.ensure_one()
        if len(self.product_variant_ids) <= 1:
            self.standard_price = value
        else:
            self.product_variant_ids.write({"standard_price": value})

    def _apihub_lines(self):
        """Líneas de proveedor que ApiHub toma en cuenta: las de Compras sin los proveedores marcados 'ApiHub no lo toma en cuenta'."""
        self.ensure_one()
        return self.seller_ids.filtered(lambda s: s.partner_id and not s.partner_id.apihub_ignore)

    def _apihub_availability_info(self):
        """(etiqueta, texto) para mostrar en la tienda, o False si el producto no se maneja o es de entrega rápida."""
        self.ensure_one()
        if self.apihub_state not in ("on_order", "out"):
            return False
        cfg = self.env["apihub.config"].sudo().get_config()
        if self.apihub_state == "on_order":
            return (_("Sobre pedido"), cfg.on_order_text or "")
        return (_("Agotado"), cfg.out_text or "")


class ResPartner(models.Model):
    _inherit = "res.partner"

    apihub_ignore = fields.Boolean(
        string="ApiHub no lo toma en cuenta", copy=False,
        help="Proveedor que se captura a mano (ej. Compuproveedores): ApiHub lo ignora al ordenar proveedores, calcular AVCO, publicar, "
             "verificar el carrito y comprar. La línea queda en Compras para tus órdenes manuales.")


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _is_add_to_cart_allowed(self):
        allowed = super()._is_add_to_cart_allowed()
        return allowed and self.product_tmpl_id.apihub_state != "out"
