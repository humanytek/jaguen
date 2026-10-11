import logging
from datetime import datetime

import pytz

from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)

MAX_TEXT = 600
FALLBACK = ("Tuve un problema técnico y no pude responderte. Escríbenos por el formulario "
            "https://www.jaguen.com/contactus o al correo contacto.jaguen@gmail.com y te atendemos.")
LIMIT_TURNS = ("Llegamos al límite de esta conversación. Si quieres seguir, escríbenos por "
               "https://www.jaguen.com/contactus y te atendemos en horario laboral.")
LIMIT_DAILY = ("Por hoy ya alcanzaste el límite de mensajes del asistente. Escríbenos por "
               "https://www.jaguen.com/contactus y te atendemos en horario laboral.")
CLOSED = "Esta conversación ya terminó. Gracias por tu interés en JAGUEN."
DISABLED = ("El asistente no está disponible por ahora. Escríbenos por https://www.jaguen.com/contactus "
            "y te atendemos en horario laboral.")


class JaguenChatController(http.Controller):

    def _session(self, token):
        if not token or len(token) > 64:
            return request.env['jaguen.chat.session']
        return request.env['jaguen.chat.session'].sudo().search([('token', '=', token)], limit=1)

    def _base_url(self):
        domain = request.website.domain if request.website else ''
        return (domain or request.httprequest.url_root).rstrip('/')

    def _greeting(self, mode, name, first_name=''):
        """Saludo segun la hora de Hermosillo. Visitante: pregunta su nombre. Cliente con sesion: lo saluda por nombre."""
        hour = datetime.now(pytz.utc).astimezone(pytz.timezone('America/Hermosillo')).hour
        saludo = 'Buenos días' if hour < 12 else ('Buenas tardes' if hour < 19 else 'Buenas noches')
        if mode == 'client':
            return "%s, te atiende %s de JAGUEN. ¿En qué te puedo apoyar%s?" % (
                saludo, name, (', %s' % first_name) if first_name else '')
        return "%s, te atiende %s de JAGUEN. ¿Con quién tengo el gusto?" % (saludo, name)

    @http.route('/jaguen/chat/status', type='json', auth='public', website=True)
    def status(self):
        return {'enabled': request.env['jaguen.ai.service'].sudo()._enabled()}

    @http.route('/jaguen/chat/start', type='json', auth='public', website=True)
    def start(self, token=None):
        service = request.env['jaguen.ai.service'].sudo()
        session = self._session(token)
        user = request.env.user
        is_client = not user._is_public()
        mode = 'client' if is_client else 'visitor'
        if session and session.state != 'closed' and session.mode == mode:
            msgs = session._widget_messages(0)
            return {'token': session.token, 'mode': mode, 'greeting': self._greeting(mode, service._ai_name(), (user.partner_id.name or '').split(' ')[0] if is_client else ''),
                    'name': service._ai_name(), 'messages': msgs, 'state': session.state,
                    'enabled': service._enabled()}
        session = request.env['jaguen.chat.session'].sudo().create({
            'name': ('Cliente: %s' % user.partner_id.name) if is_client else 'Visitante web',
            'token': request.env['jaguen.chat.session']._new_token(),
            'mode': mode, 'user_id': user.id if is_client else False,
            'partner_id': user.partner_id.id if is_client else False,
            'ip_address': request.httprequest.remote_addr or '',
        })
        session.write({'ai_model': service._model_for(session)})
        return {'token': session.token, 'mode': mode, 'greeting': self._greeting(mode, service._ai_name(), (user.partner_id.name or '').split(' ')[0] if is_client else ''),
                'name': service._ai_name(), 'messages': [], 'state': 'ai', 'enabled': service._enabled()}

    @http.route('/jaguen/chat/poll', type='json', auth='public', website=True)
    def poll(self, token=None, after_id=0):
        session = self._session(token)
        if not session:
            return {'messages': [], 'state': 'closed'}
        return {'messages': session._widget_messages(int(after_id or 0)), 'state': session.state}

    @http.route('/jaguen/chat/send', type='json', auth='public', website=True)
    def send(self, token=None, text=''):
        session = self._session(token)
        text = (text or '').strip()[:MAX_TEXT]
        if not session or not text:
            return {'messages': [], 'state': 'closed'}
        service = request.env['jaguen.ai.service'].sudo()
        Usage = request.env['jaguen.chat.usage'].sudo()
        ip = request.httprequest.remote_addr or 'sin-ip'
        key = ('user:%s' % session.user_id.id) if session.mode == 'client' else ('ip:%s' % ip)
        user_msg = session._post_visitor(text)
        out = {'user_message_id': user_msg.id, 'state': session.state}

        def bot(text_):
            msg = session._post_bot(text_)
            return [{'id': msg.id, 'role': 'assistant', 'text': text_}]

        # persona atendiendo: el mensaje queda en el chatter (ya notifica a quien sigue la conversacion)
        if session.state == 'human':
            session.sudo().write({'last_activity': fields.Datetime.now()})
            out['messages'] = []
            return out
        if session.state == 'closed':
            out['messages'] = bot(CLOSED)
            return out
        if not service._enabled():
            out['messages'] = bot(DISABLED)
            return out
        limits = service._limits(session)
        if session.turn_count >= limits['max_turns']:
            out['messages'] = bot(LIMIT_TURNS)
            return out
        if Usage._count(key) >= limits['daily'] or Usage._count('global') >= service._int_param('ai_daily_global', 600):
            out['messages'] = bot(LIMIT_DAILY)
            return out
        try:
            reply, t_in, t_out = service.reply(session, self._base_url())
        except Exception:  # noqa: BLE001
            _logger.exception('Falló la respuesta del asistente web')
            out['messages'] = bot(FALLBACK)
            return out
        Usage._bump(key, messages=1, tokens_in=t_in, tokens_out=t_out)
        Usage._bump('global', messages=1, tokens_in=t_in, tokens_out=t_out)
        session.sudo().write({'turn_count': session.turn_count + 1, 'tokens_in': session.tokens_in + t_in,
                              'tokens_out': session.tokens_out + t_out,
                              'last_activity': fields.Datetime.now()})
        msgs = []
        if reply:
            msgs += bot(reply)
        else:
            msgs += bot(FALLBACK)
        if session.segment == 'no_atendible':
            session.sudo().write({'state': 'closed'})  # se despidio: no se sigue gastando en esta conversacion
        out['messages'] = msgs
        out['state'] = session.state  # puede haber cambiado a 'human' por pasar_a_persona o a 'closed'
        return out
