{
    "name": "JAGUEN Supplier Hub (ApiHub)",
    "summary": "Costos de proveedores, orden de proveedores y publicación según existencia",
    "description": """
Actualiza cada día el costo de CT, Ingram, Loma, Syscom y Exel, ordena a los proveedores,
y publica o despublica productos según su existencia. Todo se configura desde Odoo.
Ver docs/DECISIONES.md en el repositorio ApiHub para las reglas y su razón.
""",
    "author": "JAGUEN",
    "category": "Inventory/Purchase",
    "version": "18.0.1.2.13",
    "license": "LGPL-3",
    "depends": ["product", "website_sale"],
    "data": [
        "security/ir.model.access.csv",
        "views/provider_views.xml",
        "views/link_views.xml",
        "views/config_views.xml",
        "views/menus.xml",
        "data/apihub_data.xml",
    ],
    "post_init_hook": "post_init_hook",
    "application": True,
    "installable": True,
}
