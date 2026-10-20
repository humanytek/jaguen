from odoo import fields, models


class ApihubMarketMargin(models.Model):
    _name = "apihub.market.margin"
    _description = "Margen que deja el mercado por subcategoría (Cómputo y Tecnología)"
    _order = "categ_id"

    categ_id = fields.Many2one("product.category", string="Subcategoría", required=True, ondelete="cascade", index=True)
    margin_pct = fields.Float(
        string="Margen que deja el mercado (%)", digits=(12, 2),
        help="Margen sobre el precio si se iguala el precio más bajo de la competencia (comparativo mensual: Intercompras, Cyberpuerta/Abasteo, "
             "Pedidos.com). Puede ser negativo. La lista más barata usa el mayor entre este margen y el piso de la configuración.")
    note = fields.Char(string="Nota", help="De dónde sale el número (fecha del comparativo, muestra).")
    updated_on = fields.Date(string="Actualizado", default=fields.Date.context_today)

    _sql_constraints = [("unique_categ", "unique(categ_id)", "Esa subcategoría ya tiene un margen de mercado.")]
