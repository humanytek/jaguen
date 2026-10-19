def migrate(cr, version):
    """Decision de Javier (2026-10-19, docs/DECISIONES.md 7aa): los 5 proveedores son Grupo Distribuidor.
    Aqui si se pisa lo anterior: CT, Ingram y Loma estaban como Fabrica."""
    cr.execute("UPDATE apihub_provider SET pricing_group = 'distribuidor' WHERE code IN ('ct', 'ingram', 'loma', 'syscom', 'exel')")
