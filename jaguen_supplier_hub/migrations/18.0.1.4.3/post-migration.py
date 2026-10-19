def migrate(cr, version):
    """Decisión de Javier (2026-10-19, docs/DECISIONES.md 7av): las piezas de una compra del sitio se apartan 30 minutos."""
    cr.execute("UPDATE apihub_config SET live_hold_minutes = 30")
