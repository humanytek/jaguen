def migrate(cr, version):
    """Datos del pedido por API (Javier, 2026-10-19): uso de CFDI G01, todo se recoge en Hermosillo. Formas de pago por definir con Javier
    para Loma y CT (crédito/PPD). Los pedidos por API quedan APAGADOS en todos los proveedores."""
    data = {
        "syscom": ("hermosillo", "transferencia"),
        "loma": ("1006", "PPD"),
        "ct": ("01A", "99"),
    }
    for code, (warehouse, payment) in data.items():
        cr.execute("UPDATE apihub_provider SET order_warehouse = %s, order_payment = %s WHERE code = %s AND order_warehouse IS NULL",
                   (warehouse, payment, code))
