from odoo import _, api, fields, models


class ApihubConfig(models.Model):
    """Parámetros generales de ApiHub (un solo registro)."""

    _name = "apihub.config"
    _description = "Configuración general de ApiHub"

    name = fields.Char(string="Nombre", default="Configuración general", required=True)
    dry_run = fields.Boolean(
        string="Modo simulación",
        default=True,
        help="Mientras esté activo, las corridas solo informan qué cambiarían (costos, orden de proveedores, "
             "publicación) y no modifican nada. Se usa a partir de la etapa de corrida diaria.",
    )
    min_margin_pct = fields.Float(
        string="Margen mínimo de utilidad (%)",
        default=5.0,
        help="Margen sobre el precio de venta sin IVA. Si al cambiar de proveedor en el carrito el margen queda "
             "por debajo, la compra se cancela con un aviso al cliente.",
    )
    price_ratio_min = fields.Float(
        string="Costo nuevo / histórico: mínimo", default=0.5,
        help="Si el costo nuevo de un proveedor es menor que este múltiplo de su costo anterior, no se acepta solo.",
    )
    price_ratio_max = fields.Float(
        string="Costo nuevo / histórico: máximo", default=2.0,
        help="Si el costo nuevo de un proveedor es mayor que este múltiplo de su costo anterior, no se acepta solo.",
    )
    max_failed_pct = fields.Float(
        string="Máximo de marcas/proveedores con error (%)", default=20.0,
        help="Si falla más de este porcentaje en una corrida, no se aplica nada.",
    )

    @api.model
    def get_config(self):
        """Devuelve el registro único de configuración; lo crea si no existe."""
        return self.search([], limit=1) or self.create({})

    @api.model
    def action_open_config(self):
        record = self.get_config()
        return {
            "type": "ir.actions.act_window",
            "name": _("Configuración general"),
            "res_model": self._name,
            "res_id": record.id,
            "view_mode": "form",
            "target": "current",
        }
