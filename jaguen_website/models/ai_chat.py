import secrets

from odoo import api, fields, models
from odoo.tools import html2plaintext, html_escape


class JaguenChatSession(models.Model):
    """Conversacion del asistente web. Los mensajes viven en el chatter (mail.message)."""
    _name = 'jaguen.chat.session'
    _description = 'Conversación del asistente web'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(readonly=True)
    token = fields.Char(index=True, readonly=True, copy=False)
    partner_id = fields.Many2one('res.partner', string="Cliente", readonly=True)
    user_id = fields.Many2one('res.users', string="Usuario web", readonly=True)
    ip_address = fields.Char(string="IP", readonly=True)
    mode = fields.Selection(
        [('visitor', 'Visitante sin sesión'), ('client', 'Cliente con sesión')],
        default='visitor', readonly=True)
    ai_model = fields.Char(string="Modelo", readonly=True)
    state = fields.Selection(
        [('ai', 'Atiende el asistente'), ('human', 'Atiende una persona'), ('closed', 'Cerrada')],
        default='ai', tracking=True)
    turn_count = fields.Integer(string="Mensajes del cliente", readonly=True)
    tokens_in = fields.Integer(string="Tokens de entrada", readonly=True)
    tokens_out = fields.Integer(string="Tokens de salida", readonly=True)
    lead_id = fields.Many2one('crm.lead', string="Lead", readonly=True)
    last_activity = fields.Datetime(default=fields.Datetime.now, readonly=True)
    # ---- calificacion del visitante (la hace Claude con la herramienta clasificar_visitante) ----
    segment = fields.Selection(
        [('empresa', 'Empresa o negocio'), ('pfae', 'Persona física con actividad empresarial'),
         ('persona', 'Persona (uso personal)'), ('no_atendible', 'No atendible')], readonly=True)
    company_name = fields.Char(string="Empresa", readonly=True)
    is_buyer = fields.Selection([('yes', 'Es quien compra'), ('no', 'Apoya a quien compra')], readonly=True)
    person_amount_ok = fields.Boolean(string="Compra mayor a $5,000 + IVA", readonly=True)
    alerted = fields.Boolean(readonly=True)
    alerted_contact = fields.Boolean(readonly=True)
    hot = fields.Boolean(string="Prospecto caliente", readonly=True)
    hot_reasons = fields.Char(string="Por qué es caliente", readonly=True)
    match_info = fields.Text(string="Coincidencias en CRM/Ventas", readonly=True)

    def _segment(self):
        return 'cliente' if self.mode == 'client' else (self.segment or 'sin_filtro')

    @api.model
    def _new_token(self):
        return secrets.token_urlsafe(24)

    # ---- acciones desde la vista ----
    def action_return_to_ai(self):
        self.write({'state': 'ai'})

    def action_close(self):
        self.write({'state': 'closed'})

    # ---- mensajes ----
    def _bot_partner(self):
        return self.env.ref('jaguen_website.partner_jaguen_bot').sudo()

    def _visitor_partner(self):
        return self.partner_id or self.env.ref('jaguen_website.partner_jaguen_visitor').sudo()

    def _post_as(self, partner, text):
        """Publica un mensaje visible (subtipo comentario) a nombre de `partner`."""
        body = html_escape(text).replace('\n', '<br/>')
        return self.sudo().with_context(mail_create_nosubscribe=True, mail_post_autofollow=False).message_post(
            body=body, message_type='comment', subtype_xmlid='mail.mt_comment', author_id=partner.id)

    def _post_visitor(self, text):
        return self._post_as(self._visitor_partner(), text)

    def _post_bot(self, text):
        return self._post_as(self._bot_partner(), text)

    def _role(self, message):
        bot = self._bot_partner()
        if message.author_id == bot:
            return 'assistant'
        if message.author_id.user_ids.filtered(lambda u: not u.share):
            return 'staff'
        return 'user'

    def _visible_messages(self):
        """Mensajes de la conversacion: comentarios (no notas internas ni avisos), en orden."""
        comment = self.env.ref('mail.mt_comment')
        return self.sudo().message_ids.filtered(
            lambda m: m.message_type == 'comment' and m.subtype_id == comment and m.body
        ).sorted('id')

    def _history(self, limit=12):
        """Historial para la API: solo cliente y asistente, alternando, empezando en 'user'."""
        out = []
        for m in self._visible_messages():
            role = self._role(m)
            if role == 'staff':
                continue
            text = html2plaintext(m.body or '').strip()
            if not text:
                continue
            api_role = 'assistant' if role == 'assistant' else 'user'
            if out and out[-1]['role'] == api_role:
                out[-1]['content'] += '\n' + text
            else:
                out.append({'role': api_role, 'content': text})
        out = out[-limit:]
        while out and out[0]['role'] != 'user':
            out.pop(0)
        return out

    def _widget_messages(self, after_id=0):
        res = []
        for m in self._visible_messages():
            if m.id <= after_id:
                continue
            role = self._role(m)
            if role in ('assistant', 'staff'):
                res.append({'id': m.id, 'role': role, 'text': html2plaintext(m.body or '').strip()})
        return res


class JaguenChatUsage(models.Model):
    """Contadores diarios para limitar abuso (por IP, por usuario y global)."""
    _name = 'jaguen.chat.usage'
    _description = 'Uso diario del asistente web'

    key = fields.Char(required=True, index=True)
    date = fields.Date(required=True, default=fields.Date.context_today)
    messages = fields.Integer()
    tokens_in = fields.Integer()
    tokens_out = fields.Integer()

    _sql_constraints = [('key_date_uniq', 'unique(key, date)', 'Un contador por llave y día.')]

    @api.model
    def _get(self, key):
        return self.sudo().search([('key', '=', key), ('date', '=', fields.Date.context_today(self))], limit=1)

    @api.model
    def _count(self, key):
        return self._get(key).messages

    @api.model
    def _bump(self, key, messages=0, tokens_in=0, tokens_out=0):
        rec = self._get(key)
        if rec:
            rec.write({'messages': rec.messages + messages, 'tokens_in': rec.tokens_in + tokens_in,
                       'tokens_out': rec.tokens_out + tokens_out})
        else:
            self.sudo().create({'key': key, 'messages': messages, 'tokens_in': tokens_in,
                                'tokens_out': tokens_out})
