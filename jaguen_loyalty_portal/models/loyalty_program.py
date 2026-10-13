# -*- coding: utf-8 -*-
from odoo import api, fields, models


class LoyaltyProgram(models.Model):
    _inherit = 'loyalty.program'

    x_jaguen_loyalty_group = fields.Selection(
        selection=[
            ('onboarding', 'Club JAGUEN (onboarding)'),
            ('rebate', 'Rebate Anual'),
            ('pedido_monto', 'Tu Primer Pedido de $X'),
            ('pedido_linea', 'Tu Primer Pedido por Línea'),
        ],
        string='Grupo del Portal JAGUEN',
        help=(
            "A qué uno de los 3 botones de 'Mis Puntos' pertenece este "
            "programa. 'onboarding' y 'rebate' comparten el primer botón "
            "(se muestra uno u otro según si el cliente ya tiene Objetivo "
            "del año capturado); 'pedido_monto' y 'pedido_linea' son cada "
            "uno su propio botón, con todos sus tramos agrupados adentro."
        ),
    )


class LoyaltyReward(models.Model):
    _inherit = 'loyalty.reward'

    @api.model
    def _jaguen_quitar_tarjeta_rebate(self):
        """Rebate Anual es SOLO la nota de credito del 3% a la empresa: se borra cualquier tramo viejo de
        "tarjeta de regalo" que haya quedado en una base (idea descartada)."""
        viejos = self.sudo().with_context(active_test=False).search([
            ('program_id.x_jaguen_loyalty_group', '=', 'rebate'),
            ('description', 'ilike', 'tarjeta de regalo'),
        ])
        viejos.unlink()
