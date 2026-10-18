from odoo import fields, models


class ApihubSpecialPrice(models.Model):
    _name = "apihub.special.price"
    _description = "Precio especial de un proveedor (lista aparte de su página)"
    _order = "provider_id, brand, provider_sku"
    _rec_name = "provider_sku"

    provider_id = fields.Many2one("apihub.provider", string="Proveedor", required=True, ondelete="cascade", index=True)
    brand = fields.Char(string="Marca")
    provider_sku = fields.Char(string="Clave del proveedor", required=True, index=True,
                               help="La clave tal como viene en la lista de precios (ej. NE-423).")
    barcode = fields.Char(string="Código de barras")
    description = fields.Char(string="Descripción")
    list_price = fields.Float(string="Precio de lista", digits=(12, 2))
    cost = fields.Float(string="Costo especial", digits=(12, 2), required=True,
                        help="Lo que nos cuesta, sin IVA. Mientras no se cargue otra lista, el módulo usa este costo "
                             "en lugar del que publica la página del proveedor.")
    list_name = fields.Char(string="Lista", help="Nombre de la lista de la que salió, ej. 'Octubre 2026'.")
    loaded_on = fields.Date(string="Cargada el", default=fields.Date.context_today)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("unique_sku", "unique(provider_id, provider_sku)", "Esa clave ya tiene un precio especial para este proveedor."),
    ]
