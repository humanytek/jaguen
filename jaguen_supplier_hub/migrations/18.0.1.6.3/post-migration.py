def migrate(cr, version):
    """Existencia ilimitada (campo `unlimited_stock`): queda disponible pero apagado en todos los proveedores. Javier (2026-10-20): las
    tiendas locales (Costco, Home Depot, Steren, Sablon, Amazon, Walmart, Sam's) solo actualizan costo y AVCO; no publican ni despublican."""
    cr.execute("UPDATE apihub_provider SET unlimited_stock = FALSE")
