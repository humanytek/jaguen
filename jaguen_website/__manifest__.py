{
    'name': 'JAGUEN - Sitio web',
    'summary': 'Ajustes del sitio: PayPal, ruta interna oculta y H1 de la Tienda',
    'description': """
Ajustes del sitio web de JAGUEN
===============================

- PayPal: manda solo el primer correo valido del cliente (PayPal rechaza varios separados por coma).
- Oculta /website/info (lista de aplicaciones instaladas) al publico: solo personal interno.
- Agrega un titulo principal (H1) oculto a /shop para SEO.
- Pago con PayPal: pregunta obligatoria credito/debito; marca la transaccion del carrito; pago y factura salen con forma 04 / 28 y la factura PUE. No afecta pagos manuales ni facturas PPD.
- Pago: casilla obligatoria de T&C antes del metodo de pago; se autocompleta si el cliente ya la acepto antes; se guarda fecha e IP.
- Resumen diario por correo (19:30 Hermosillo) al usuario de relevo.
- Asistente web con IA (Ale, Mónica y Andrea, con Claude): Haiku filtra al visitante conversando; Sonnet atiende a empresas y clientes con
  sesion; busca productos, crea leads, avisa de prospectos calientes y de coincidencias en CRM/Ventas. Requiere el parametro de sistema jaguen_website.anthropic_api_key.
""",
    'version': '18.0.1.9.0',
    'category': 'Website',
    'author': 'JAGUEN',
    'license': 'LGPL-3',
    'depends': ['payment_paypal', 'website', 'website_sale', 'l10n_mx_edi_website_sale', 'crm', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/ai_data.xml',
        'views/shop_templates.xml',
        'views/payment_templates.xml',
        'views/ai_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'jaguen_website/static/src/js/payment_form.js',
            'jaguen_website/static/src/js/chat_widget.js',
            'jaguen_website/static/src/css/chat_widget.css',
        ],
    },
    'installable': True,
    'application': False,
}
