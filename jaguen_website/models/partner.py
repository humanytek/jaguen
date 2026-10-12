from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    jaguen_tyc_date = fields.Datetime(
        string='Aceptó T&C en el pago', readonly=True, copy=False,
        help='Última vez que el cliente marcó la casilla de términos y condiciones al pagar en el sitio.')
