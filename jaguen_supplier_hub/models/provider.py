from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ApihubProvider(models.Model):
    _name = "apihub.provider"
    _description = "Proveedor de ApiHub"
    _order = "sequence, name"

    name = fields.Char(string="Nombre", required=True)
    code = fields.Selection(
        [("ct", "CT"), ("ingram", "Ingram"), ("loma", "Loma"), ("syscom", "Syscom"), ("exel", "Exel"),
         ("costco", "Costco"), ("electronisonora", "Electronisonora (Steren)"), ("homedepot", "Home Depot"), ("sablon", "Acrílicos Sablon")],
        string="Clave", required=True,
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    partner_id = fields.Many2one("res.partner", string="Proveedor en Odoo", ondelete="set null")
    partner_pattern = fields.Char(
        string="Texto para ubicar al proveedor",
        help="Parte del nombre del proveedor en Odoo; se usa para ligarlo automáticamente al instalar.",
    )
    source_type = fields.Selection(
        [("file", "Archivo (FTP/SFTP)"), ("api", "API"), ("robot", "Robot del portal"), ("web", "Páginas de la tienda")],
        string="Fuente de datos", default="api",
    )
    native_currency = fields.Selection(
        [("MXN", "Pesos"), ("USD", "Dólares"), ("mixed", "Mixto (cada producto trae su moneda)")],
        string="Moneda del proveedor", default="MXN",
    )
    fx_source = fields.Selection(
        [("odoo", "Tipo de cambio de Odoo (Banco de México / DOF)"),
         ("provider", "El que publica el proveedor"),
         ("fixed", "Uno fijo")],
        string="Tipo de cambio a usar", default="odoo", required=True,
    )
    fx_fixed_rate = fields.Float(string="Tipo de cambio fijo", digits=(12, 4))
    min_stock = fields.Integer(
        string="Mínimo de existencia", default=3,
        help="Por debajo de este número de piezas el proveedor no cuenta para publicar ni para ordenar proveedores.",
    )
    max_data_age_hours = fields.Integer(
        string="Antigüedad máxima del dato (horas)", default=36,
        help="Si el archivo o la respuesta del proveedor es más viejo, el proveedor se trata como 'sin dato confiable'.",
    )
    purchase_delivery_note = fields.Text(
        string="Nota de entrega en la orden de compra",
        help="Se escribe en los términos de la orden de compra que ApiHub crea al confirmar una venta (por ejemplo, dónde se recoge). "
             "Javier (2026-10-19): por ahora todo se recoge en la sucursal de Hermosillo.")
    order_warehouse = fields.Char(
        string="Sucursal / almacén de entrega del pedido",
        help="Dónde se recoge lo que se compra por API: Syscom = código de la sucursal (hermosillo), Loma = clave del almacén (1006), "
             "CT = código del almacén (01A). Javier (2026-10-19): todo se recoge en Hermosillo.")
    order_payment = fields.Char(
        string="Forma de pago del pedido",
        help="Syscom: transferencia (o sucursal-credito para tarjeta). Loma: PUE o PPD. CT: 99 = crédito CT. Por definir con Javier para Loma y CT.")
    order_cfdi = fields.Char(string="Uso de CFDI del pedido", default="G01", help="Javier (2026-10-19): siempre G01.")
    order_comment = fields.Char(string="Comentario del pedido", default="Recoger en sucursal Hermosillo")
    order_ct_envio = fields.Text(
        string="Envío para CT (JSON)", default="[]",
        help="Solo CT: arreglo JSON del objeto 'envio' de su API de pedidos (nombre, direccion, entreCalles, noExterior, noInterior, colonia, estado, "
             "ciudad, codigoPostal, telefono). Su documentación no trae un campo para 'recoger en sucursal': con [] se manda sin envío; por probar "
             "con la respuesta de CT.")
    order_sandbox = fields.Boolean(
        string="Pedidos en el sandbox (pruebas)", default=True,
        help="Solo CT: mientras esté activo, las solicitudes y confirmaciones de pedidos van al ambiente de pruebas de CT "
             "(http://sandbox.ctonline.mx), no a tu cuenta real. Se apaga solo cuando Javier lo apruebe.")
    api_order_enabled = fields.Boolean(
        string="Enviar pedidos por API",
        help="Candado: mientras esté apagado, el botón 'Enviar pedido' de la orden de compra no manda nada a este proveedor. "
             "Se enciende solo con la aprobación de Javier, proveedor por proveedor.")
    live_check = fields.Boolean(
        string="Verificar en vivo en el carrito", default=False,
        help="Si está activo, al agregar al carrito y antes de pagar se consulta la existencia a este proveedor (solo Syscom, Loma y CT "
             "tienen consulta; requiere sus credenciales). Apagado = se usa el archivo del día. CT está apagado: Odoo.sh no llega a su API.")
    on_order_fee = fields.Float(
        string="Cargo de envío sobre pedido ($, sin IVA)", default=100.0,
        help="Se suma al envío del cliente, una sola vez por pedido, cuando el carrito trae productos 'Sobre pedido' cuyo "
             "Proveedor 1 es este. Si hay varios proveedores en el carrito se cobra el mayor. El IVA lo pone el método de envío.")
    freight_amount = fields.Float(
        string="Flete por producto ($)", default=100.0,
        help="Se suma al costo cuando la existencia no está en un almacén sin flete.",
    )
    freight_only_tech = fields.Boolean(
        string="Flete solo en Cómputo y Tecnología", default=True,
        help="Si está activo, el flete solo se suma en productos de esa categoría; en lo demás se compara el precio tal cual.",
    )
    cost_factor = fields.Float(
        string="Factor sobre el costo del archivo", default=1.0, digits=(12, 4),
        help="Se multiplica al costo que trae el archivo o la API del proveedor (no a los precios especiales cargados aparte). "
             "Sirve para un descuento que el portal aplica y la API no muestra (ej. 0.96 = 4 % menos). 1 = sin cambio.",
    )
    avco_factor = fields.Float(
        string="Factor de flete del AVCO", default=1.0, digits=(12, 4),
        help="El AVCO de un producto sin existencia es el costo de su Proveedor 1 por este factor.",
    )
    pricing_group = fields.Selection(
        [("fabrica", "Grupo Fábrica (precio fijo en Página; las demás listas encadenadas a Página)"),
         ("distribuidor", "Grupo Distribuidor (fórmula sobre el costo en todas las listas)")],
        string="Grupo de precios",
        help="Decide cómo se arma la regla de precio de venta de los productos cuyo Proveedor 1 es este. "
             "Nunca se infiere del nombre: lo confirma Javier (docs/DECISIONES.md, sección 7o).",
    )
    order_code_source = fields.Selection(
        [("provider_ref", "ID/clave interno del proveedor"), ("provider_sku", "Número de parte"), ("none", "No se escribe")],
        string="Código en la orden de compra", default="none",
        help="Qué código del proveedor se escribe en la línea de proveedor del producto (Código del producto del proveedor) "
             "al aprobar una equivalencia, para que la orden de compra salga con el código que ese proveedor usa. "
             "'No se escribe' = se deja lo que ya tiene Odoo (nuestra descripción y código).",
    )
    price_freight_pct = fields.Float(
        string="Flete para el precio de venta (%)", default=0.0, digits=(12, 2),
        help="Solo Grupo Fábrica: se suma al AVCO antes de aplicar el margen. En la Fase 1 (entrega local) es 0.",
    )
    price_margin_pct = fields.Float(
        string="Margen de Fábrica sobre el precio (%)", default=30.0, digits=(12, 2),
        help="Solo Grupo Fábrica: precio fijo SOLO en la lista Página = AVCO × (1 + flete) ÷ (1 − margen), redondeado a 0.25. "
             "Javier (2026-10-19): 'Fábrica es el 30 % de margen siempre, en Página solamente'.",
    )
    price_discount_pct = fields.Float(
        string="Descuento del proveedor (%)", default=0.0, digits=(12, 2),
        help="Descuento que aplica el proveedor sobre su lista. En la Fase 1 es 0.",
    )
    has_stock_data = fields.Boolean(
        string="Da existencia", default=True,
        help="Los proveedores de tienda (Costco, Home Depot, Steren) solo dan precio: sin existencia confiable, así que los "
             "productos cuyo proveedor es uno de estos no se publican ni se despublican solos (siguen a mano).")
    card_fee_pct = fields.Float(
        string="Cargo de tarjeta (%)", default=0.0, digits=(12, 2),
        help="Solo proveedores de tienda: se suma al precio de la página (Costco 2 %).")
    tax_pct = fields.Float(
        string="IVA (%)", default=16.0, digits=(12, 2),
        help="Solo proveedores de tienda: el precio de la página trae IVA en los productos marcados 'El precio trae IVA'; "
             "el costo se guarda sin IVA.")
    last_sync_at = fields.Datetime(string="Última corrida", readonly=True)
    last_data_date = fields.Datetime(string="Fecha del dato del proveedor", readonly=True)
    notes = fields.Text(string="Notas")
    warehouse_rule_ids = fields.One2many("apihub.warehouse.rule", "provider_id", string="Almacenes y reglas")
    credential_ids = fields.One2many("apihub.provider.credential", "provider_id", string="Credenciales")

    _sql_constraints = [("code_unique", "unique(code)", "Ya existe un proveedor con esa clave.")]

    # ------------------------------------------------------------------ tipo de cambio
    def get_usd_mxn_rate(self, date=None):
        """Pesos por dólar según el tipo de cambio que tiene Odoo (Banco de México / DOF si está activo)."""
        usd = self.env.ref("base.USD")
        mxn = self.env.ref("base.MXN")
        date = date or fields.Date.context_today(self)
        has_rate = self.env["res.currency.rate"].sudo().search_count(
            [("currency_id", "=", usd.id), ("company_id", "in", (False, self.env.company.id))])
        if not usd.active or not has_rate:
            # sin esto Odoo devolvería 1.0 y los costos en dólares se tomarían como pesos
            raise UserError(_("Odoo no tiene tipo de cambio para USD (moneda inactiva o sin tasas). "
                              "Activa USD y la actualización automática de monedas (Banco de México)."))
        return self.env["res.currency"]._get_conversion_rate(usd, mxn, self.env.company, date)

    def to_mxn(self, amount, currency="MXN", provider_rate=None, date=None):
        """Convierte un monto del proveedor a pesos con la regla de tipo de cambio configurada."""
        self.ensure_one()
        currency = (currency or "MXN").upper()
        if currency == "MXN":
            return amount
        if currency != "USD":
            raise UserError(_("Moneda no soportada: %s", currency))
        if self.fx_source == "fixed":
            rate = self.fx_fixed_rate
        elif self.fx_source == "provider" and provider_rate:
            rate = provider_rate
        else:
            rate = self.get_usd_mxn_rate(date)
        if not rate:
            raise UserError(_("No hay tipo de cambio disponible para convertir %s a pesos.", currency))
        return amount * rate

    def action_test_fx(self):
        self.ensure_one()
        usd = self.env.ref("base.USD")
        latest = self.env["res.currency.rate"].sudo().search([("currency_id", "=", usd.id)], order="name desc", limit=1)
        if latest and usd.active:
            rate = self.get_usd_mxn_rate()
            message = _("1 USD = %(rate).4f MXN. Último tipo de cambio cargado en Odoo: %(date)s.",
                        rate=rate, date=latest.name)
            kind = "success"
            if (fields.Date.context_today(self) - latest.name).days > 3:
                message += " " + _("Tiene más de 3 días: revisa la actualización automática de monedas.")
                kind = "warning"
        else:
            message = _("Odoo no tiene tipo de cambio para USD. Activa la actualización automática de monedas "
                        "(Banco de México) o captura uno.")
            kind = "danger"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"title": _("Tipo de cambio"), "message": message, "type": kind, "sticky": False},
        }


class ApihubWarehouseRule(models.Model):
    _name = "apihub.warehouse.rule"
    _description = "Regla de almacén de un proveedor"
    _order = "provider_id, sequence, code"

    provider_id = fields.Many2one("apihub.provider", string="Proveedor", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    code = fields.Char(
        string="Clave del almacén", required=True,
        help="Clave tal como la entrega el proveedor (por ejemplo HMO, 1006, hermosillo). Con * vale cualquier almacén.",
    )
    name = fields.Char(string="Nombre")
    counts_for_publication = fields.Boolean(string="Cuenta para publicar", default=True)
    free_shipping = fields.Boolean(string="Sin flete", default=True)
    min_stock_override = fields.Integer(
        string="Mínimo propio", default=0,
        help="Si es mayor que 0, reemplaza el mínimo de existencia del proveedor para este almacén.",
    )
    active = fields.Boolean(default=True)


class ApihubProviderCredential(models.Model):
    _name = "apihub.provider.credential"
    _description = "Credencial de un proveedor"

    provider_id = fields.Many2one("apihub.provider", string="Proveedor", required=True, ondelete="cascade")
    key = fields.Char(string="Nombre", required=True)
    value = fields.Char(string="Valor", groups="base.group_system")
