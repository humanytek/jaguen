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
