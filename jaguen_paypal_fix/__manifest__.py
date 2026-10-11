{
    'name': 'JAGUEN - Arreglo de correos en pagos con PayPal',
    'summary': 'PayPal rechazaba el pago cuando el cliente tiene varios correos en el campo Correo',
    'description': """
Arreglo de correos en pagos con PayPal
======================================

Muchos clientes de JAGUEN guardan varios correos separados por coma en el campo "Correo"
(para enviarles las facturas). PayPal solo acepta un correo y, al recibir varios, rechaza el
pago con el error "Request is not well-formed, syntactically incorrect, or violates schema".

Este modulo le manda a PayPal solamente el primer correo valido de ese campo. No cambia ni
borra nada de los datos del cliente en Odoo, y no guarda datos.
""",
    'version': '18.0.1.0.0',
    'category': 'Accounting/Payment Providers',
    'author': 'JAGUEN',
    'license': 'LGPL-3',
    'depends': ['payment_paypal'],
    'data': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}
