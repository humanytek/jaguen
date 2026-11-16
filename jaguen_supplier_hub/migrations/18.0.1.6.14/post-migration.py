def migrate(cr, version):
    """Javier, 2026-11-16: Ebenezer cuenta como fuente de FABRICA (no se reordena y el precio de venta sale de el) y Tuksonora entrega
    local siempre. Los registros de proveedor estan en noupdate: al actualizar el modulo no se reescriben, por eso se hace aqui."""
    cr.execute("UPDATE apihub_provider SET pricing_group = 'fabrica' WHERE code = 'ebenezer'")
    cr.execute("UPDATE apihub_provider SET local_source = TRUE WHERE code = 'tuksonora'")
