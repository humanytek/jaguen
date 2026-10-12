from odoo import fields, models


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    jaguen_portal_visible = fields.Boolean(
        string='Visible en Mis documentos', copy=False,
        help='Documentos que el cliente subió (registro o Mi cuenta) y que él mismo puede ver y descargar.')
