{
    'name': 'JAGUEN - Sitio web',
    'summary': 'Ajustes del sitio: PayPal, ruta interna oculta y H1 de la Tienda',
    'description': """
Ajustes del sitio web de JAGUEN
===============================

- PayPal: manda solo el primer correo valido del cliente (PayPal rechaza varios separados por coma).
- Oculta /website/info (lista de aplicaciones instaladas) al publico: solo personal interno.
- Agrega un titulo principal (H1) oculto a /shop para SEO.
""",
    'version': '18.0.1.1.0',
    'category': 'Website',
    'author': 'JAGUEN',
    'license': 'LGPL-3',
    'depends': ['payment_paypal', 'website', 'website_sale'],
    'data': ['views/shop_templates.xml'],
    'installable': True,
    'application': False,
}
