# -*- coding: utf-8 -*-
import logging

from odoo import api, models

from .gift_catalog import GIFT_CATALOG

_logger = logging.getLogger(__name__)

# Fecha de puesta en marcha del programa en produccion (ver fix_onboarding_automations).
ONBOARDING_DESDE = '2026-10-10 00:00:00'
GIFT_PROGRAM_TAG = {'starter': 'tag_regalo_starter_%s', 'mpp': 'tag_regalo_mpp_%s'}


class JaguenGiftSetup(models.AbstractModel):
    _name = 'jaguen.gift.setup'
    _description = 'Carga de regalos de JAGUEN Starter y Mi Primer Pedido'

    @api.model
    def _find_product(self, code, name):
        """Producto real por codigo interno (o por nombre si el regalo no trae codigo)."""
        Product = self.env['product.product'].sudo()
        if code:
            return Product.search([('default_code', '=', code)], limit=1)
        return Product.search([('name', '=', name)], limit=1)

    @api.model
    def setup_gifts(self):
        """Pone cada regalo del catalogo en la etiqueta de su nivel.

        Usa los productos que ya existen en Odoo (se buscan por codigo
        interno); NUNCA crea productos. Es seguro correrlo varias veces: deja en cada etiqueta exactamente los
        productos del catalogo."""
        Product = self.env['product.product'].sudo()
        # Las etiquetas son internas: no deben verse en la tienda en linea.
        self.env['product.tag'].sudo().search(
            [('name', '=like', 'Regalo %'), ('visible_on_ecommerce', '=', True)]
        ).write({'visible_on_ecommerce': False})
        wanted = {}
        missing = []
        for program, amount, code, name, cost, provider in GIFT_CATALOG:
            tag = self.env.ref('jaguen_loyalty_portal.' + GIFT_PROGRAM_TAG[program] % amount)
            product = self._find_product(code, name)
            if not product:
                # No se crean productos: si falta uno, se salta y se avisa.
                missing.append(code or name)
                continue
            # Etiqueta a nivel de VARIANTE: asi un producto con tallas (como la
            # bota) solo ofrece la talla elegida y no todas.
            product.write({'additional_product_tag_ids': [(4, tag.id)]})
            wanted.setdefault(tag.id, set()).add(product.id)
        for tag_id, product_ids in wanted.items():
            stale = Product.with_context(active_test=False).search([
                '|', ('additional_product_tag_ids', 'in', [tag_id]), ('product_tag_ids', 'in', [tag_id]),
                ('id', 'not in', list(product_ids))])
            if stale:
                stale.write({
                    'additional_product_tag_ids': [(3, tag_id)],
                    'product_tag_ids': [(3, tag_id)],
                })
        if missing:
            _logger.warning('Regalos sin producto en Odoo (no se crearon): %s', missing)
        return missing

    @api.model
    def gift_order(self, program, amount):
        """Orden (codigo o nombre) de las opciones de un nivel, segun el catalogo."""
        return [c or n for p, a, c, n, _cost, _prov in GIFT_CATALOG if p == program and a == amount]

    @api.model
    def setup_language(self):
        """Idioma por defecto de los contactos: espanol (es_MX).

        Evita que los contactos nuevos (y sus PDF/correos) salgan en ingles.
        Tambien pone espanol a los contactos que no tienen idioma. No cambia
        a los que ya tienen otro idioma asignado. Seguro de correr varias veces."""
        lang = self.env['res.lang'].sudo().search([('code', '=', 'es_MX'), ('active', '=', True)], limit=1)
        if not lang:
            _logger.warning("jaguen_loyalty_portal: es_MX no esta activo; no se cambia el idioma por defecto.")
            return False
        self.env['ir.default'].sudo().set('res.partner', 'lang', 'es_MX')
        self.env['res.partner'].sudo().with_context(active_test=False).search([('lang', '=', False)]).write({'lang': 'es_MX'})
        return True

    @api.model
    def fix_onboarding_automations(self):
        """Las automatizaciones de onboarding (aviso de 2 semanas y aviso de
        4 meses) solo deben aplicar a clientes NUEVOS (dados de alta desde la
        puesta en marcha del programa) que activaron JAGUEN Starter. Sin este filtro, al instalar el modulo
        en una base con clientes de antes, Odoo les manda el aviso y crea la
        actividad a todos los que ya cumplieron esos plazos.

        La fecha de inicio se guarda en el parametro del sistema
        jaguen_loyalty_portal.onboarding_desde (se puede cambiar). Seguro de
        correr varias veces."""
        Param = self.env['ir.config_parameter'].sudo()
        desde = Param.get_param('jaguen_loyalty_portal.onboarding_desde')
        if not desde:
            desde = ONBOARDING_DESDE
            Param.set_param('jaguen_loyalty_portal.onboarding_desde', desde)
        # Solo clientes nuevos, que SI activaron JAGUEN Starter (aceptaron los Incentivos
        # Starter) y que todavia no pasaron a Rebate Anual (sin Objetivo del ano).
        domain = repr([
            ('create_date', '>=', desde),
            ('parent_id', '=', False),
            ('x_acepta_incentivos_personales', '=', True),
            ('x_objetivo_anual_programa2', 'in', [0, False]),
        ])
        for xmlid in ('automation_aviso_2_semanas', 'automation_fin_onboarding_avisar_javier'):
            rule = self.env.ref('jaguen_loyalty_portal.' + xmlid, raise_if_not_found=False)
            if rule:
                rule.sudo().write({'filter_domain': domain})
        return True
