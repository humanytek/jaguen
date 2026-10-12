# -*- coding: utf-8 -*-
"""Dos cupones publicos (se ven y se aplican solos en el carrito de la tienda, a diferencia de los 4
programas JAGUEN que solo reclama un vendedor desde el backend, ver sale_order_jaguen.py):

1. Cupon Registro ($200, ya incluye IVA): se entrega por correo en cuanto termina el registro web
   (empresa, PFAE o compra personal). Minimo de compra $4,000. Vence a los 30 dias; se manda un
   recordatorio 5 dias antes si no se uso. Uno por cliente, de por vida.
2. Cupon Favoritos ($500, ya incluye IVA): se entrega en cuanto el cliente llega a 40 productos
   guardados en favoritos (compartido por toda la empresa). Se "congela" la foto de esos 40
   productos exactos en ese momento; para poder USAR el cupon, la compra debe incluir al menos 20
   de esos 40 (no importa si despues cambio sus favoritos). Sin vencimiento. Uno por cliente, de
   por vida.

Los montos reales en Odoo son $431 y $172.50 antes de IVA (asi el total con IVA da $499.96 y
$200.10, sin pelearse con un tercer decimal); en toda pantalla, correo y texto SIEMPRE se habla de
"$500" y "$200" redondos.
"""
import logging
import secrets

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

PROGRAM_REGISTRO_XMLID = 'jaguen_loyalty_portal.program_cupon_registro'
PROGRAM_FAVORITOS_XMLID = 'jaguen_loyalty_portal.program_cupon_favoritos'
FAVORITOS_REQUERIDOS = 40
FAVORITOS_MINIMO_COMPRA = 20
REGISTRO_DIAS_VIGENCIA = 30


def _jaguen_new_code(prefix):
    return '%s-%s' % (prefix, secrets.token_hex(4).upper())


class LoyaltyProgramJaguenCoupons(models.Model):
    _inherit = 'loyalty.program'

    def _jaguen_public_amount(self):
        """Monto redondo a mostrar en pantalla (nunca el real con decimales: $431/$172.50 son el
        valor ANTES de IVA que se guarda en Odoo para que el total con IVA salga limpio)."""
        self.ensure_one()
        raw = self.reward_ids[:1].discount
        return 500 if raw and raw > 300 else 200


class LoyaltyCardJaguenCoupons(models.Model):
    _inherit = 'loyalty.card'

    # Foto de los 40 productos que el cliente tenia guardados cuando se le dio el Cupon Favoritos.
    # Se llena una sola vez al crear la tarjeta y nunca se vuelve a tocar: el cupon se revisa
    # siempre contra ESTA lista, no contra los favoritos actuales del cliente.
    x_jaguen_frozen_products = fields.Many2many('product.product', string='Favoritos congelados (Cupón)', copy=False)
    jaguen_reminder_sent = fields.Boolean(string='Recordatorio de vencimiento enviado', copy=False)


class ResPartnerJaguenCoupons(models.Model):
    _inherit = 'res.partner'

    def _jaguen_finish_registration(self, forced=None):
        super()._jaguen_finish_registration(forced=forced)
        try:
            self._jaguen_grant_welcome_coupon()
        except Exception:  # noqa: BLE001 - un fallo aqui no debe tumbar el registro
            _logger.exception('Cupón Registro: no se pudo otorgar a %s', self.id)
            self.sudo().with_context(mail_notrack=True).message_post(
                body='No se pudo generar el Cupón Registro de este cliente. Revisar a mano.', subtype_xmlid='mail.mt_note')

    def _jaguen_grant_welcome_coupon(self):
        """Cupon Registro: uno por cliente de por vida, se manda por correo al terminar el alta web."""
        self.ensure_one()
        program = self.env.ref(PROGRAM_REGISTRO_XMLID, raise_if_not_found=False)
        if not program:
            return
        Card = self.env['loyalty.card'].sudo()
        commercial = self.commercial_partner_id
        if Card.search_count([('partner_id', '=', commercial.id), ('program_id', '=', program.id)]):
            return  # ya tuvo uno alguna vez
        reward = program.reward_ids[:1]
        card = Card.create({
            'partner_id': commercial.id,
            'program_id': program.id,
            'points': reward.required_points if reward else 1,
            'code': _jaguen_new_code('BIENVENIDO'),
            'expiration_date': fields.Date.context_today(self) + relativedelta(days=REGISTRO_DIAS_VIGENCIA),
        })
        self._jaguen_send_coupon_mail(self, 'jaguen_loyalty_portal.mail_template_cupon_bienvenida', card)

    @api.model
    def _jaguen_send_coupon_mail(self, partner, template_xmlid, card):
        """Manda el correo del cupon al partner indicado. Si falla (plantilla, render, correo sin
        servidor, etc.) NUNCA tumba el flujo que lo llama: deja una nota interna con el codigo para
        que se pueda dar a mano, y registra el error en el log."""
        if not partner.email:
            return
        template = self.env.ref(template_xmlid, raise_if_not_found=False)
        if not template:
            return
        try:
            template.sudo().with_context(jaguen_card_id=card.id).send_mail(
                partner.id, force_send=True, email_values={'email_to': partner.email})
        except Exception:  # noqa: BLE001
            _logger.exception('Cupón: no se pudo mandar el correo (plantilla %s) a %s', template_xmlid, partner.id)
            partner.sudo().with_context(mail_notrack=True).message_post(
                body='No se pudo mandar el correo del cupón %s (%s). Dáselo a mano.' % (card.code, partner.email),
                subtype_xmlid='mail.mt_note')

    @api.model
    def _jaguen_cron_recordar_cupon_registro(self):
        """Recordatorio 5 dias antes de que venza el Cupon Registro, si sigue sin usarse."""
        program = self.env.ref(PROGRAM_REGISTRO_XMLID, raise_if_not_found=False)
        if not program:
            return
        hoy = fields.Date.context_today(self)
        avisar = hoy + relativedelta(days=5)
        Card = self.env['loyalty.card'].sudo()
        cards = Card.search([
            ('program_id', '=', program.id), ('expiration_date', '=', avisar),
            ('use_count', '=', 0), ('jaguen_reminder_sent', '=', False),
        ])
        for card in cards:
            self._jaguen_send_coupon_mail(card.partner_id, 'jaguen_loyalty_portal.mail_template_cupon_por_vencer', card)
            card.jaguen_reminder_sent = True


class ProductWishlistJaguenCoupons(models.Model):
    _inherit = 'product.wishlist'

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        partners = records.mapped('partner_id').mapped('commercial_partner_id')
        for partner in partners:
            try:
                self._jaguen_grant_favoritos_coupon(partner)
            except Exception:  # noqa: BLE001 - un fallo aqui no debe tumbar el guardado del favorito
                _logger.exception('Cupón Favoritos: no se pudo revisar/otorgar a %s', partner.id)
        return records

    def _jaguen_grant_favoritos_coupon(self, commercial_partner):
        """Cupon Favoritos: uno por cliente de por vida, al llegar a 40 favoritos (sumando toda la
        empresa). Congela esos 40 productos exactos (los 40 mas antiguos) en el cupon."""
        if not commercial_partner or not commercial_partner.id:
            return
        program = self.env.ref(PROGRAM_FAVORITOS_XMLID, raise_if_not_found=False)
        if not program:
            return
        Card = self.env['loyalty.card'].sudo()
        if Card.search_count([('partner_id', '=', commercial_partner.id), ('program_id', '=', program.id)]):
            return  # ya tuvo uno alguna vez
        partners = self._jaguen_company_partners(commercial_partner)
        wishes = self.sudo().search([('partner_id', 'in', partners.ids)], order='id asc', limit=FAVORITOS_REQUERIDOS)
        if len(wishes) < FAVORITOS_REQUERIDOS:
            return
        products = wishes.mapped('product_id')
        reward = program.reward_ids[:1]
        card = Card.create({
            'partner_id': commercial_partner.id,
            'program_id': program.id,
            'points': reward.required_points if reward else 1,
            'code': _jaguen_new_code('FAVORITOS'),
            'x_jaguen_frozen_products': [(6, 0, products.ids)],
        })
        self.env['res.partner']._jaguen_send_coupon_mail(commercial_partner, 'jaguen_loyalty_portal.mail_template_cupon_favoritos', card)


class SaleOrderJaguenCoupons(models.Model):
    _inherit = 'sale.order'

    def _get_claimable_rewards(self, forced_coupons=None):
        """El Cupon Favoritos solo se puede reclamar si la compra trae al menos 20 de los 40
        productos que tenia guardados cuando se le dio el cupon (la foto congelada, no sus
        favoritos actuales)."""
        result = super()._get_claimable_rewards(forced_coupons=forced_coupons)
        favoritos = self.env.ref(PROGRAM_FAVORITOS_XMLID, raise_if_not_found=False)
        if not favoritos:
            return result
        order_products = set(self.order_line.filtered(lambda l: not l.display_type).mapped('product_id').ids)
        for coupon in list(result):
            if coupon.program_id == favoritos:
                frozen = set(coupon.x_jaguen_frozen_products.ids)
                if len(order_products & frozen) < FAVORITOS_MINIMO_COMPRA:
                    del result[coupon]
        return result

    def _update_programs_and_rewards(self):
        """Los 2 cupones publicos no esperan a que el cliente escriba el codigo: en cuanto el
        carrito ya los puede reclamar (cumple el minimo, o trae 20 de los 40 favoritos), se ponen
        solos. (Odoo ya los MUESTRA como reclamables via _get_claimable_rewards; aqui falta nada
        mas reclamarlos de una vez cuando trigger='auto'.)"""
        super()._update_programs_and_rewards()
        if not self.website_id:
            return
        programs = (self.env.ref(PROGRAM_REGISTRO_XMLID, raise_if_not_found=False)
                    | self.env.ref(PROGRAM_FAVORITOS_XMLID, raise_if_not_found=False))
        if not programs:
            return
        already = self.order_line.filtered('reward_id').mapped('coupon_id')
        claimable = self._get_claimable_rewards()
        for coupon, rewards in claimable.items():
            if coupon.program_id in programs and coupon not in already and rewards:
                try:
                    self._apply_program_reward(rewards[0], coupon)
                except Exception:  # noqa: BLE001 - si no se pudo aplicar solo, el cliente lo aplica con el boton
                    _logger.exception('Cupón: no se pudo auto-aplicar %s en el pedido %s', coupon.code, self.id)

    def _jaguen_available_public_coupons(self):
        """Cupones vigentes y sin usar del cliente (de los 2 programas publicos), para mostrarlos
        en el carrito sin que tenga que buscar en su correo."""
        self.ensure_one()
        # Sin sesion (visitante) el pedido queda a nombre del partner publico generico: no tiene cupones propios.
        if not self.partner_id or self.partner_id == self.env.ref('base.public_partner', raise_if_not_found=False):
            return self.env['loyalty.card']
        programs = (self.env.ref(PROGRAM_REGISTRO_XMLID, raise_if_not_found=False)
                    | self.env.ref(PROGRAM_FAVORITOS_XMLID, raise_if_not_found=False))
        if not programs:
            return self.env['loyalty.card']
        hoy = fields.Date.context_today(self)
        domain = [
            ('partner_id', '=', self.partner_id.commercial_partner_id.id),
            ('program_id', 'in', programs.ids),
            ('use_count', '=', 0),
            '|', ('expiration_date', '=', False), ('expiration_date', '>=', hoy),
        ]
        return self.env['loyalty.card'].sudo().search(domain)
