def migrate(cr, version):
    """Tiendas con existencia ilimitada (Javier, 2026-10-20): Costco, Home Depot y Steren. Sablon sigue a mano hasta que Javier diga."""
    cr.execute("UPDATE apihub_provider SET unlimited_stock = TRUE WHERE code IN ('costco', 'homedepot', 'electronisonora')")
