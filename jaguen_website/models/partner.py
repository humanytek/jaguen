import re
import unicodedata

from odoo import api, fields, models
from odoo.exceptions import AccessError

# Nombres femeninos que NO terminan en "a" y masculinos que SI terminan en "a" (el resto se decide por la terminacion).
_FEMALE = {'guadalupe', 'carmen', 'beatriz', 'mercedes', 'lourdes', 'soledad', 'raquel', 'esther', 'ruth', 'miriam', 'ines',
           'isabel', 'maribel', 'rocio', 'pilar', 'dolores', 'consuelo', 'concepcion', 'abigail', 'noemi', 'edith', 'karen',
           'sharon', 'nicole', 'jennifer', 'jessica', 'liz', 'iris', 'maite', 'araceli', 'yaneth', 'jazmin', 'celeste',
           'berenice', 'monserrat', 'montserrat', 'mariel', 'ivonne', 'yvonne', 'noelia', 'marisol', 'cruz', 'luz', 'paz'}
_MALE_A = {'luca', 'borja', 'joshua', 'garcia', 'bautista', 'kaleb', 'ezra', 'sasha', 'misha', 'nikita'}
_TITLES = {'lic', 'ing', 'dr', 'dra', 'mtro', 'mtra', 'arq', 'c', 'cp', 'sr', 'sra', 'srta', 'don', 'dona'}


def _first_name(name):
    text = unicodedata.normalize('NFD', (name or '').lower())
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    for token in re.sub(r'[^a-z ]', ' ', text).split():
        if token not in _TITLES:
            return token
    return ''


def guess_gender(name):
    """'f', 'm' o None segun el primer nombre (lo mejor posible; si no se sabe, no se pone titulo)."""
    first = _first_name(name)
    if len(first) < 3:
        return None
    if first in _FEMALE:
        return 'f'
    if first.endswith('a') and first not in _MALE_A:
        return 'f'
    return 'm'


class ResPartner(models.Model):
    _inherit = 'res.partner'

    jaguen_wishlist_count = fields.Integer(string="Favoritos", compute="_compute_jaguen_wishlist_count")

    def _jaguen_wishlist_domain(self):
        self.ensure_one()
        return [('partner_id', 'child_of', self.id)]

    def _compute_jaguen_wishlist_count(self):
        Wish = self.env['product.wishlist'].sudo()
        for p in self:
            p.jaguen_wishlist_count = Wish.search_count(p._jaguen_wishlist_domain()) if p.id else 0

    def action_jaguen_wishlist(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Favoritos de %s' % self.display_name,
            'res_model': 'product.wishlist',
            'view_mode': 'list',
            'domain': self._jaguen_wishlist_domain(),
            'context': {'search_default_g_product': 0},
        }

    jaguen_tyc_date = fields.Datetime(
        string='Aceptó T&C en el pago', readonly=True, copy=False,
        help='Última vez que el cliente marcó la casilla de términos y condiciones al pagar en el sitio.')

    # Campos de paso del formulario "Regístrate": se usan al crear el registro y no se guardan.
    jaguen_contact_name = fields.Char(copy=False)
    jaguen_contact_email = fields.Char(copy=False)
    jaguen_contact_mobile = fields.Char(copy=False)
    jaguen_contact_function = fields.Char(copy=False)
    jaguen_ship_same = fields.Char(copy=False)
    jaguen_ship_street = fields.Char(copy=False)
    jaguen_ship_colony = fields.Char(copy=False)
    jaguen_ship_zip = fields.Char(copy=False)
    jaguen_ship_city = fields.Char(copy=False)
    jaguen_ship_state = fields.Char(copy=False)
    jaguen_ship_receiver = fields.Char(copy=False)
    jaguen_ship_phone = fields.Char(copy=False)
    jaguen_ship_email = fields.Char(copy=False)

    _JAGUEN_STEP_FIELDS = ('jaguen_contact_name', 'jaguen_contact_email', 'jaguen_contact_mobile', 'jaguen_contact_function',
                           'jaguen_ship_same', 'jaguen_ship_street', 'jaguen_ship_colony', 'jaguen_ship_zip',
                           'jaguen_ship_city', 'jaguen_ship_state', 'jaguen_ship_receiver', 'jaguen_ship_phone', 'jaguen_ship_email')

    @api.model_create_multi
    def create(self, vals_list):
        steps = []
        for vals in vals_list:
            steps.append({k: (vals.pop(k, None) or '').strip() for k in self._JAGUEN_STEP_FIELDS})
        records = super().create(vals_list)
        for rec, step in zip(records, steps):
            if not rec.parent_id and (step['jaguen_contact_name'] or step['jaguen_ship_receiver'] or step['jaguen_ship_street']):
                rec._jaguen_create_children(step)
        return records

    def _jaguen_title(self, name):
        gender = guess_gender(name)
        if not gender:
            return self.env['res.partner.title']
        return self.env.ref('jaguen_website.title_senorita' if gender == 'f' else 'jaguen_website.title_senor',
                            raise_if_not_found=False) or self.env['res.partner.title']

    def _jaguen_create_children(self, step):
        """Registro: la empresa queda con el correo de facturacion; la persona que se registra (comprador) y la
        direccion de entrega se crean como contactos dentro de la empresa."""
        self.ensure_one()
        Partner = self.sudo().with_context(mail_create_nosubscribe=True, mail_notrack=True, tracking_disable=True)
        if not self.is_company:
            self.sudo().write({'company_type': 'company'})
        if step['jaguen_contact_name']:
            Partner.create({
                'parent_id': self.id, 'type': 'contact', 'name': step['jaguen_contact_name'][:80],
                'title': self._jaguen_title(step['jaguen_contact_name']).id or False,
                'email': step['jaguen_contact_email'][:80] or False, 'mobile': step['jaguen_contact_mobile'][:40] or False,
                'function': step['jaguen_contact_function'][:80] or False,
            })
        # Direccion de entrega: contacto de tipo "entrega" con la persona autorizada para recibir mercancia.
        same = step['jaguen_ship_same'].lower() in ('', 'igual', 'si', 'sí', '1', 'true', 'on', 'yes')
        receiver = step['jaguen_ship_receiver']
        if receiver or (step['jaguen_ship_street'] and not same):
            mx = self.env.ref('base.mx', raise_if_not_found=False)
            if same or not step['jaguen_ship_street']:
                addr = {'street': self.street, 'street2': self.street2, 'zip': self.zip, 'city': self.city,
                        'state_id': self.state_id.id, 'country_id': self.country_id.id or (mx.id if mx else False)}
            else:
                state = False
                if step['jaguen_ship_state']:
                    state = self.env['res.country.state'].sudo().search(
                        [('country_id.code', '=', 'MX'), ('name', 'ilike', step['jaguen_ship_state'])], limit=1)
                addr = {'street': step['jaguen_ship_street'][:120], 'street2': step['jaguen_ship_colony'][:80] or False,
                        'zip': step['jaguen_ship_zip'][:10] or False, 'city': step['jaguen_ship_city'][:60] or False,
                        'state_id': state.id if state else False, 'country_id': mx.id if mx else False}
            Partner.create(dict(addr, **{
                'parent_id': self.id, 'type': 'delivery', 'name': (receiver or 'Dirección de entrega')[:80],
                'title': self._jaguen_title(receiver).id or False if receiver else False,
                'email': step['jaguen_ship_email'][:80] or False, 'mobile': step['jaguen_ship_phone'][:40] or False}))

    # ---------- mover el usuario del portal de la empresa al contacto ----------
    def action_jaguen_move_user_here(self):
        """El usuario de portal esta pegado a la EMPRESA (saluda 'Hola <empresa>') y no se puede dar acceso al contacto
        porque su correo ya es login. Se pasa ese mismo usuario al contacto: mismo login, contrasena e historial."""
        if not self.env.user.has_group('base.group_system'):
            raise AccessError('Solo un administrador puede pasar un usuario de portal a otro contacto.')
        moved = self.env['res.users']
        for contact in self:
            company = contact.parent_id
            if not company or contact.user_ids:
                continue
            users = company.user_ids.filtered(lambda u: u.share and u.active)
            if len(users) != 1:
                continue
            user = users
            contact_s = contact.sudo()
            if not contact_s.email:
                contact_s.with_context(mail_notrack=True).write({'email': user.login})
            user.sudo().with_context(mail_notrack=True, no_reset_password=True).write({'partner_id': contact_s.id})
            moved |= user
        return moved


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model
    def action_jaguen_fix_company_users(self):
        """Usuarios de portal pegados a una EMPRESA: crea (o reutiliza) el contacto de la persona y le pasa el usuario.
        El nombre sale del correo cuando no se sabe (adalberto@x.com -> Adalberto; juan.perez@x.com -> Juan Perez)."""
        if not self.env.user.has_group('base.group_system'):
            raise AccessError('Solo un administrador puede corregir los usuarios de portal.')
        report = []
        Partner = self.env['res.partner'].sudo().with_context(mail_create_nosubscribe=True, mail_notrack=True, tracking_disable=True)
        users = self.sudo().search([('share', '=', True), ('active', '=', True), ('partner_id.is_company', '=', True)])
        for user in users:
            company = user.partner_id
            contact = company.child_ids.filtered(
                lambda c: c.type == 'contact' and (c.email or '').strip().lower() == (user.login or '').strip().lower())[:1]
            if not contact:
                local = (user.login or '').split('@')[0]
                guess = ' '.join(w.capitalize() for w in re.split(r'[._\-+]+', local) if w and not w.isdigit()) or 'Contacto'
                contact = Partner.create({'parent_id': company.id, 'type': 'contact', 'name': guess, 'email': user.login,
                                          'title': company._jaguen_title(guess).id or False})
            contact.action_jaguen_move_user_here()
            report.append((company.name, user.login, contact.name))
        return report
