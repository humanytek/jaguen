import logging
import re
from datetime import datetime

import pytz

from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)

MAX_TEXT = 600
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$')
FALLBACK = ("Tuve un problema técnico y no pude responderte. Escríbenos por el formulario "
            "https://www.jaguen.com/contactus o al correo contacto.jaguen@gmail.com y te atendemos.")
LIMIT_TURNS = ("Llegamos al límite de esta conversación. Si quieres seguir, escríbenos por "
               "https://www.jaguen.com/contactus y te atendemos en horario laboral.")
LIMIT_DAILY = ("Por hoy ya alcanzaste el límite de mensajes del asistente. Escríbenos por "
               "https://www.jaguen.com/contactus y te atendemos en horario laboral.")
CLOSED = "Esta conversación ya terminó. Gracias por tu interés en Jaguen."
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
            return "%s, te atiende %s de Jaguen. ¿En qué te puedo apoyar%s?" % (
                saludo, name, (', %s' % first_name) if first_name else '')
        return "%s, te atiende %s de Jaguen. ¿Con quién tengo el gusto?" % (saludo, name)

    @http.route('/jaguen/chat/status', type='json', auth='public', website=True)
    def status(self):
        service = request.env['jaguen.ai.service'].sudo()
        return {'enabled': service._enabled(), 'agents': service._ai_names()}

    @http.route('/jaguen/chat/start', type='json', auth='public', website=True)
    def start(self, token=None):
        service = request.env['jaguen.ai.service'].sudo()
        session = self._session(token)
        user = request.env.user
        is_client = not user._is_public()
        mode = 'client' if is_client else 'visitor'
        if not is_client and service._prechat() and not (session and session.state != 'closed' and session.mode == mode):
            return {'need_form': True, 'enabled': service._enabled()}
        if session and session.state != 'closed' and session.mode == mode:
            if not session.agent_name:
                session.write({'agent_name': service._pick_name()})
            msgs = session._widget_messages(0)
            return {'token': session.token, 'mode': mode,
                    'greeting': '' if msgs else self._greeting(mode, session.agent_name, (user.partner_id.name or '').split(' ')[0] if is_client else ''),
                    'name': session.agent_name, 'messages': msgs, 'state': session.state,
                    'enabled': service._enabled()}
        session = request.env['jaguen.chat.session'].sudo().create({
            'name': ('Cliente: %s' % user.partner_id.name) if is_client else 'Visitante web',
            'token': request.env['jaguen.chat.session']._new_token(),
            'mode': mode, 'user_id': user.id if is_client else False,
            'partner_id': user.partner_id.id if is_client else False,
            'ip_address': request.httprequest.remote_addr or '',
        })
        session.write({'ai_model': service._model_for(session), 'agent_name': service._pick_name()})
        return {'token': session.token, 'mode': mode, 'greeting': self._greeting(mode, session.agent_name, (user.partner_id.name or '').split(' ')[0] if is_client else ''),
                'name': session.agent_name, 'messages': [], 'state': 'ai', 'enabled': service._enabled()}

    @http.route('/jaguen/chat/start_form', type='json', auth='public', website=True)
    def start_form(self, nombre='', empresa='', correo='', telefono='', personal=False, hp='', agente=''):
        """Formulario previo al chat: valida, crea la conversacion, el lead y el saludo."""
        service = request.env['jaguen.ai.service'].sudo()
        if not service._enabled():
            return {'error': 'disabled'}
        if hp:  # campo trampa para bots
            return {'error': 'spam'}
        if not request.env.user._is_public():
            return {'error': 'logged'}
        nombre, empresa, correo = (nombre or '').strip()[:80], (empresa or '').strip()[:80], (correo or '').strip()[:80]
        telefono, personal = (telefono or '').strip()[:30], bool(personal)
        errors = {}
        if len(nombre) < 2:
            errors['nombre'] = 'Escribe tu nombre.'
        if not personal and len(empresa) < 2:
            errors['empresa'] = 'Escribe el nombre de tu empresa o marca "Es compra personal".'
        if not EMAIL_RE.match(correo):
            errors['correo'] = 'Escribe un correo válido.'
        if not 10 <= len(re.sub(r'\D', '', telefono)) <= 13:
            errors['telefono'] = 'Escribe un teléfono de 10 dígitos.'
        if errors:
            return {'errors': errors}
        Usage = request.env['jaguen.chat.usage'].sudo()
        key = 'form:%s' % (request.httprequest.remote_addr or 'sin-ip')
        if Usage._count(key) >= service._int_param('ai_daily_forms_ip', 10):
            return {'error': 'limit'}
        Usage._bump(key, messages=1)
        session = request.env['jaguen.chat.session'].sudo().create({
            'name': 'Visitante web: %s' % (empresa or nombre),
            'token': request.env['jaguen.chat.session']._new_token(),
            'mode': 'visitor', 'ip_address': request.httprequest.remote_addr or '',
            'contact_name': nombre, 'contact_email': correo, 'contact_phone': telefono,
            'company_name': '' if personal else empresa, 'personal_purchase': personal,
            'agent_name': agente if agente in service._ai_names() else service._pick_name(),
        })
        service._start_from_form(session)
        session.write({'ai_model': service._model_for(session)})
        return {'token': session.token, 'name': session.agent_name, 'messages': session._widget_messages(0),
                'state': session.state}

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
