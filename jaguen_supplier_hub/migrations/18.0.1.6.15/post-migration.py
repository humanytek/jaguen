def migrate(cr, version):
    """Javier, 2026-11-16: Ebenezer tiene el orden manual (no se reordena) y Tuksonora entrega local. Solo eso: no se mueve nada de lo
    que ya funcionaba (las tiendas Steren, Costco y Home Depot NO se tocan). Los registros de proveedor estan en noupdate."""
    cr.execute("UPDATE apihub_provider SET manual_order = TRUE WHERE code = 'ebenezer'")
    cr.execute("UPDATE apihub_provider SET local_source = TRUE WHERE code = 'tuksonora'")
