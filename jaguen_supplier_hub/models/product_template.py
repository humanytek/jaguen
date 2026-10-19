from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    apihub_state = fields.Selection(
        [("local", "Entrega rápida"), ("on_order", "Sobre pedido"), ("out", "Agotado")],
        string="Disponibilidad (ApiHub)", copy=False,
        help="La calcula la corrida de publicación con la existencia de los proveedores.")
    apihub_out_since = fields.Date(
        string="Agotado desde (ApiHub)", copy=False,
        help="Primer día de la racha de días en que ningún proveedor lo tiene. A los días configurados se despublica.")
