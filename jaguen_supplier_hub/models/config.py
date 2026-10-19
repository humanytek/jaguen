from odoo import _, api, fields, models


class ApihubConfig(models.Model):
    """Parámetros generales de ApiHub (un solo registro)."""

    _name = "apihub.config"
    _description = "Configuración general de ApiHub"

    name = fields.Char(string="Nombre", default="Configuración general", required=True)
    main_lang = fields.Char(
        string="Idioma de referencia", default="es_MX", required=True,
        help="Idioma en el que se comparan nombres y descripciones (marca y código). Es el que se ve y se captura en Odoo; "
             "los demás idiomas pueden traer copias viejas.")
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
    daily_change_pct = fields.Float(
        string="Cambio de un día a otro que se frena (±%)", default=10.0,
        help="Si el costo de un proveedor cambia más que esto de un día a otro, no se aplica el primer día (puede ser un error).")
    peer_tolerance_pct = fields.Float(
        string="Tolerancia para confirmar con otros proveedores (puntos)", default=3.0,
        help="El cambio se aplica de inmediato si los demás proveedores del producto se movieron igual, con esta diferencia.")
    sale_pricelist_ids = fields.Many2many(
        "product.pricelist", "apihub_config_pricelist_rel", "config_id", "pricelist_id", string="Listas de precios de venta",
        help="Las listas en las que el motor crea la regla de precio que falte (una regla de fórmula por producto y lista). "
             "Los porcentajes se copian de las reglas que ya existen en esas listas, nunca están en el código.",
    )
    public_pricelist_id = fields.Many2one(
        "product.pricelist", string="Lista de precio público",
        help="La lista que ve cualquiera sin iniciar sesión (Página). Con ella el motor revisa que el precio público no quede "
             "por debajo del precio mínimo que fija el proveedor (ej. Syscom, precio MAP).",
    )
    p1_change_pct = fields.Float(
        string="Ahorro mínimo para cambiar de Proveedor 1 (%)", default=2.0,
        help="El Proveedor 1 actual se queda mientras su costo efectivo no sea más de este porcentaje mayor que el mejor. "
             "Evita que cambie todos los días por centavos (propuesta 2 %, por confirmar).")
    on_order_text = fields.Char(
        string="Texto de 'Sobre pedido' en la página", translate=True,
        default="2 - 4 días hábiles",
        help="Se muestra junto a la etiqueta 'Sobre pedido' en la ficha del producto (plazo de entrega).")
    out_text = fields.Char(
        string="Texto de 'Agotado' en la página", translate=True,
        default="")
    unpublish_days = fields.Integer(
        string="Días agotado para despublicar", default=30,
        help="Un producto que ningún proveedor tiene durante estos días seguidos se despublica.")
    max_unpublish_pct = fields.Float(
        string="Freno: máximo de despublicaciones en una corrida (%)", default=10.0,
        help="Si una corrida fuera a despublicar más que este porcentaje de los productos que maneja (mínimo 5), no despublica "
             "ninguno: algo raro pasó con los datos.")
    max_failed_pct = fields.Float(
        string="Máximo de marcas/proveedores con error (%)", default=20.0,
        help="Si falla más de este porcentaje en una corrida, no se aplica nada.",
    )

    live_mode = fields.Selection(
        [("off", "Apagada"), ("observe", "Solo observar (registra, no bloquea)"), ("on", "Activa")],
        string="Verificación en vivo en el carrito", default="off", required=True,
        help="Al agregar al carrito y antes de pagar consulta la existencia a Syscom, Loma y CT (Exel e Ingram siguen con el "
             "archivo del día). 'Solo observar' deja el registro en ApiHub -> Verificaciones en vivo sin cambiar la compra.")
    live_reserve_hours = fields.Integer(
        string="Horas que cuentan las piezas ya vendidas", default=24,
        help="Las piezas de órdenes de venta confirmadas (no cotizaciones) de las últimas horas que todavía no se entregan se descuentan de la existencia del "
             "proveedor (aún no se las has comprado). Pasado ese tiempo se asume que ya se compraron y la existencia del proveedor ya bajó. "
             "0 = no descontar.")
    live_hold_minutes = fields.Integer(
        string="Minutos que se apartan las piezas de una compra del sitio", default=30,
        help="Cuando el cliente termina su compra en el sitio (queda como cotización) se apartan sus piezas durante este tiempo, para que "
             "otro cliente no las pida. Si no se firma/acepta o se paga a tiempo, las piezas se liberan solas. 0 = no apartar.")
    purchase_mode = fields.Selection(
        [("off", "Apagado"), ("draft", "Crear órdenes de compra en borrador")],
        string="Compras al confirmar una venta", default="off", required=True,
        help="Cuando se confirma una orden de venta, ApiHub reparte lo que falta (lo que no cubre tu inventario propio) entre los proveedores "
             "y crea una orden de compra en BORRADOR por proveedor, con un aviso para revisarla y enviarla. No envía nada al proveedor.")
    purchase_user_id = fields.Many2one(
        "res.users", string="Quién revisa las compras",
        help="Recibe la actividad 'revisar y enviar' de cada orden de compra en borrador. Si está vacío, el vendedor de la orden o el administrador.")
    live_timeout = fields.Integer(
        string="Tiempo máximo de espera al proveedor (segundos)", default=6,
        help="Si el proveedor no responde en este tiempo, la compra sigue con el dato del archivo y el pedido queda con la "
             "nota 'verificar disponibilidad'.")

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
