# -*- coding: utf-8 -*-
from odoo import fields, models


class ResUsersColumnas(models.Model):
    """Guarda en el servidor las columnas opcionales que cada persona elige en las listas de Odoo (ventas, compras,
    contabilidad, etc.). Odoo las guarda solo en el navegador y las pierde al cambiar de equipo o cuando cambia la vista."""
    _inherit = 'res.users'

    x_jaguen_cols = fields.Text(string='Columnas elegidas en las listas (JAGUEN)', copy=False)

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + ['x_jaguen_cols']

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + ['x_jaguen_cols']
