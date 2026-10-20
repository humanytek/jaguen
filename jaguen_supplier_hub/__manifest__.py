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
    "version": "18.0.1.6.8",
    "license": "LGPL-3",
    "depends": ["product", "stock", "purchase", "website_sale", "delivery"],
    "data": [
        "security/ir.model.access.csv",
        "views/provider_views.xml",
        "views/link_views.xml",
        "views/special_price_views.xml",
        "views/market_margin_views.xml",
        "views/run_log_views.xml",
        "views/config_views.xml",
        "views/website_templates.xml",
        "views/purchase_views.xml",
        "views/product_views.xml",
        "views/menus.xml",
        "data/apihub_data.xml",
    ],
    "post_init_hook": "post_init_hook",
    "application": True,
    "installable": True,
}
