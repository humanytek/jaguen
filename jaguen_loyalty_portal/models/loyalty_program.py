# -*- coding: utf-8 -*-
from odoo import fields, models


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

    x_jaguen_reward_audience = fields.Selection(
        selection=[
            ('empresa', 'Empresa (nota de crédito)'),
            ('comprador', 'Comprador (Incentivo Starter)'),
        ],
        string='A quién va este tramo (JAGUEN)',
        help=(
            "Solo se usa en Rebate Anual, donde un mismo nivel de "
            "cumplimiento reparte dos cosas distintas: una nota de "
            "crédito a la empresa y una tarjeta de regalo a quien "
            "gestiona la cuenta. El portal oculta los tramos marcados "
            "'comprador' si ese cliente no aceptó Incentivos Starter. "
            "Vacío = se muestra siempre (es el caso normal, para el resto "
            "de los programas)."
        ),
    )
