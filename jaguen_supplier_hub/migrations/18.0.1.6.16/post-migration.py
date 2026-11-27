def migrate(cr, version):
    """Javier, 2026-11-27: Casa Myers entra al ApiHub como proveedor de tienda (Grupo Distribuidor). El registro del proveedor lo crea
    apihub_data.xml; aqui solo se liga con el proveedor de Odoo, porque post_init_hook corre unicamente al INSTALAR el modulo."""
    cr.execute(
        """UPDATE apihub_provider SET partner_id = (
               SELECT id FROM res_partner WHERE name ILIKE %s AND active ORDER BY id LIMIT 1)
           WHERE code = 'casamyers' AND partner_id IS NULL""",
        ("%casa myers%",))
