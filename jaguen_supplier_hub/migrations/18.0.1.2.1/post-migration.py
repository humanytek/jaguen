def migrate(cr, version):
    """Tipo de cambio por proveedor (decision de Javier, 2026-10-18; ver docs/DECISIONES.md 7p):
    si el proveedor cotiza en dolares se usa el tipo de cambio de Odoo (Banxico); si cotiza en pesos con su
    propio tipo de cambio (asi factura), se usa el de ellos. Solo cambia donde sigue en el valor de arranque."""
    for code in ("syscom", "loma"):
        cr.execute("UPDATE apihub_provider SET fx_source = 'provider' WHERE code = %s AND fx_source = 'odoo'", (code,))

    # Codigo que cada proveedor recibe en una orden (documentacion de sus APIs, 2026-10-18):
    # CT: clave; Loma: 'sku' largo de POST /pedido; Syscom: 'id' numerico de POST /api/v1/carrito/generar.
    # Exel e Ingram no tienen API de pedidos: se deja lo que ya tiene Odoo.
    for code, source in (("ct", "provider_ref"), ("loma", "provider_ref"), ("syscom", "provider_ref"),
                         ("ingram", "none"), ("exel", "none")):
        cr.execute("UPDATE apihub_provider SET order_code_source = %s WHERE code = %s AND (order_code_source IS NULL OR order_code_source = 'none')", (source, code))
