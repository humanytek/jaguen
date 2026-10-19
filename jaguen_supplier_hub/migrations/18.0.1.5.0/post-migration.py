def migrate(cr, version):
    """Javier (2026-10-19): por ahora lo que se le compra a un proveedor se recoge en su sucursal de Hermosillo (docs 7ax)."""
    notes = {
        "loma": "Entrega: recoger en la sucursal Hermosillo (almacén 1006).",
        "syscom": "Entrega: recoger en la sucursal Hermosillo.",
        "ct": "Entrega: recoger en la sucursal Hermosillo (no en Cedis). Si el producto está en Cedis, enviarlo a la sucursal Hermosillo.",
    }
    for code, text in notes.items():
        cr.execute("UPDATE apihub_provider SET purchase_delivery_note = %s WHERE code = %s AND purchase_delivery_note IS NULL", (text, code))
