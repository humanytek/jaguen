def migrate(cr, version):
    """Verificación en vivo del carrito (docs/DECISIONES.md 7as): solo Syscom y Loma se consultan en vivo desde Odoo.sh.
    CT queda apagado (su API no es alcanzable desde Odoo.sh); Exel e Ingram no tienen consulta."""
    cr.execute("UPDATE apihub_provider SET live_check = (code IN ('syscom', 'loma'))")
