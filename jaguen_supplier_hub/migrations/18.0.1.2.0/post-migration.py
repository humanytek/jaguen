def migrate(cr, version):
    """Grupo de precios por proveedor (medido en produccion el 2026-10-18; ver docs/DECISIONES.md 7o).
    Solo llena donde esta vacio: nunca pisa lo que Javier haya cambiado."""
    groups = {"ct": "fabrica", "ingram": "fabrica", "loma": "fabrica", "syscom": "distribuidor", "exel": "distribuidor"}
    for code, group in groups.items():
        cr.execute("UPDATE apihub_provider SET pricing_group = %s WHERE code = %s AND pricing_group IS NULL", (group, code))
