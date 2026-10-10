# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.http import request


class ResPartner(models.Model):
    _inherit = 'res.partner'

    x_objetivo_anual_programa2 = fields.Float(
        string='Objetivo del año (Programa 2 - Rebate Anual, MXN)',
        help=(
            "Meta anual de compra de este cliente para el cálculo del "
            "rebate de Programa 2. Se captura manualmente por cliente. "
            "Mientras esté vacío (0), el cliente se considera en "
            "onboarding (Club JAGUEN); en cuanto se captura un número, "
            "pasa a Programa 2 (ver automatizaciones en Odoo)."
        ),
    )

    # -- Candado de Términos y Condiciones del portal de lealtad --------
    x_terminos_portal_respondido = fields.Boolean(
        string='Ya paso por la pantalla de Terminos del portal de lealtad',
        help=(
            "Se marca en cuanto el cliente envia el formulario de "
            "Terminos y Condiciones de 'Mis Puntos' (acepte o no cada "
            "casilla). Mientras este en False, el portal le muestra esa "
            "pantalla antes de dejarlo ver cualquier programa."
        ),
    )
    x_terminos_portal_fecha = fields.Datetime(
        string='Fecha de respuesta a Terminos del portal de lealtad',
    )
    x_acepta_incentivos_personales = fields.Boolean(
        string='Acepta Incentivos Starter',
        help=(
            "Controla los regalos/vales que se entregan a la persona que "
            "gestiona la cuenta, en representacion de la empresa (JAGUEN "
            "Starter, Mi Primer Pedido de $X, Mi Primer Pedido por Linea, "
            "y la tarjeta de regalo dentro de Rebate Anual). Si esta en "
            "False, esos programas se ocultan por completo en el portal "
            "de ese cliente."
        ),
    )
    x_acepta_rebate_anual = fields.Boolean(
        string='Acepta participar en Rebate Anual',
        help=(
            "Controla el programa de Rebate Anual completo (nota de "
            "credito a la empresa, mas la tarjeta de regalo si tambien "
            "acepto Incentivos Starter). Si esta en False, ese programa "
            "no se muestra en el portal de ese cliente."
        ),
    )

    @api.model_create_multi
    def create(self, vals_list):
        # Todo lo que se registra por la pagina /registrate (formulario del
        # sitio web) se guarda como Empresa en Contactos, sea persona fisica
        # o moral; las personas que compran son contactos hijos de esa
        # empresa. Aplica aunque el formulario ya no pregunte "Tipo de
        # empresa".
        try:
            from_form = bool(request) and request.httprequest.path.startswith('/website/form')
        except RuntimeError:
            from_form = False
        if from_form:
            for vals in vals_list:
                if not vals.get('parent_id'):
                    vals['company_type'] = 'company'
        return super().create(vals_list)
