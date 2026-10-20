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

    def _apihub_availability_info(self):
        """(etiqueta, texto) para mostrar en la tienda, o False si el producto no se maneja o es de entrega rápida."""
        self.ensure_one()
        if self.apihub_state not in ("on_order", "out"):
            return False
        cfg = self.env["apihub.config"].sudo().get_config()
        if self.apihub_state == "on_order":
            return (_("Sobre pedido"), cfg.on_order_text or "")
        return (_("Agotado"), cfg.out_text or "")


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _is_add_to_cart_allowed(self):
        allowed = super()._is_add_to_cart_allowed()
        return allowed and self.product_tmpl_id.apihub_state != "out"
