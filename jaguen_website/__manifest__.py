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
- Aviso interno (bandeja y correo) al vendedor del pedido y a contabilidad cuando un cliente paga en linea.
- Pago: casilla obligatoria de T&C antes del metodo de pago; se autocompleta si el cliente ya la acepto antes; se guarda fecha e IP.
- Leads del chat en la etapa Web del pipeline, con actividad para Javier y la plática en las notas internas.
- Consulta de pedidos con candado (número + nombre o correo; 3 intentos y bloqueo de 60 minutos).
- Registro: empresa con correo de facturación + contacto comprador (título Sr./Srta. automático) + dirección de entrega; Mi cuenta > Mis documentos (con actividad al vendedor por documentos de crédito); botón para pasar el usuario de la empresa al contacto.
- Resumen diario por correo (19:30 Hermosillo) al usuario de relevo.
- Asistente web con IA (Ale, Mónica y Andrea, con Claude): Haiku filtra al visitante conversando; Sonnet atiende a empresas y clientes con
  sesion; busca productos, crea leads, avisa de prospectos calientes y de coincidencias en CRM/Ventas. Requiere el parametro de sistema jaguen_website.anthropic_api_key.
""",
    'version': '18.0.1.22.34',
    'category': 'Website',
    'author': 'JAGUEN',
    'license': 'LGPL-3',
    'depends': ['payment_paypal', 'website', 'website_sale', 'website_sale_wishlist', 'l10n_mx_edi_website_sale', 'l10n_mx_edi_extended', 'crm', 'mail', 'portal'],
    'data': [
        'security/ir.model.access.csv',
        'data/ai_data.xml',
        'data/partner_data.xml',
        'data/rotation_data.xml',
        'data/form_whitelist.xml',
        'views/shop_templates.xml',
        'views/payment_templates.xml',
        'views/order_templates.xml',
        'views/portal_templates.xml',
        'views/ai_views.xml',
        'views/wishlist_views.xml',
        'views/columnas_views.xml',
        'views/cart_personal.xml',
        'views/back_to_cart.xml',
        'data/sepomex_load.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'jaguen_website/static/src/js/columnas_persistentes.js',
        ],
        'web.assets_frontend': [
            'jaguen_website/static/src/js/payment_form.js',
            'jaguen_website/static/src/js/chat_widget.js',
            'jaguen_website/static/src/js/registrate_cp.js',
            'jaguen_website/static/src/css/chat_widget.css',
        ],
    },
    'installable': True,
    'application': False,
}
