from datetime import datetime, time, timedelta

import pytz
from markupsafe import Markup, escape

from odoo import models

# USD por millon de tokens: (entrada, salida). Lectura de cache = 10% de la entrada; escritura = 125%.
_PRICES = {'haiku': (0.10, 0.50), 'sonnet': (2.0, 10.0)}
_SEG = {'empresa': 'Empresa', 'pfae': 'Persona física con act. empresarial', 'persona': 'Compra personal',
        'no_atendible': 'No atendible', 'cliente': 'Cliente con sesión', False: 'Sin clasificar'}


class JaguenChatSessionDigest(models.Model):
    _inherit = 'jaguen.chat.session'

    def _digest_cost(self):
        total = 0.0
        for s in self:
            price = _PRICES['haiku'] if 'haiku' in (s.ai_model or '') else _PRICES['sonnet']
            fresh = max((s.tokens_in or 0) - (s.tokens_cache_read or 0) - (s.tokens_cache_write or 0), 0)
            total += (fresh * price[0] + (s.tokens_cache_read or 0) * price[0] * 0.1
                      + (s.tokens_cache_write or 0) * price[0] * 1.25 + (s.tokens_out or 0) * price[1]) / 1e6
        return total

    def _cron_daily_digest(self):
        """Resumen diario del asistente web por correo (conversaciones del dia, hora de Hermosillo)."""
        service = self.env['jaguen.ai.service']
        if service._param('ai_digest_enabled', '1') not in ('1', 'True', 'true'):
            return
        tz = pytz.timezone('America/Hermosillo')
        today = datetime.now(pytz.utc).astimezone(tz).date()
        start = tz.localize(datetime.combine(today, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        end = start + timedelta(days=1)
        sessions = self.sudo().search([('create_date', '>=', start), ('create_date', '<', end)], order='create_date')
        if not sessions:
            return
        user = self.env['res.users'].sudo().search([('login', '=', service._param('ai_handoff_login'))], limit=1)
        to = service._param('ai_digest_to') or (user.partner_id.email or user.email or '')
        if not to:
            return
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        counts = {}
        for s in sessions:
            counts[s.segment or False] = counts.get(s.segment or False, 0) + 1
        hot = sessions.filtered('hot')
        humans = sessions.filtered(lambda s: s.state == 'human')
        matches = sessions.filtered('match_info')
        cost = sessions._digest_cost()
        rows = Markup('')
        for s in sessions:
            who = ' · '.join(x for x in [s.contact_name, s.company_name, s.contact_phone, s.contact_email] if x) or s.name
            flags = ' '.join(f for f in [' 🔥 caliente' if s.hot else '', ' ⚠️ coincide con CRM' if s.match_info else '',
                                         ' 🙋 pasó a persona' if s.state == 'human' else ''] if f)
            link = '%s/odoo/action-%s/%s' % (base, 'jaguen_website.action_jaguen_chat_session', s.id)
            rows += Markup('<tr><td style="padding:4px 8px;border-bottom:1px solid #e5e7eb">%s</td>'
                           '<td style="padding:4px 8px;border-bottom:1px solid #e5e7eb">%s<br/><span style="color:#6b7280">%s · %s · atendió %s · %s turnos</span>%s</td></tr>') % (
                s.create_date.replace(tzinfo=pytz.utc).astimezone(tz).strftime('%H:%M'), who,
                _SEG.get(s.segment, s.segment), 'Sonnet' if 'sonnet' in (s.ai_model or '') else 'Haiku',
                s.agent_name or '-', s.turn_count or 0, Markup(' <b>%s</b>') % flags if flags else '')
        summary = Markup(
            '<p><b>%s conversaciones</b> hoy: %s.</p>'
            '<p>Leads calientes: <b>%s</b> · Pasaron a persona: <b>%s</b> · Coinciden con CRM/Ventas: <b>%s</b>.</p>'
            '<p>Costo aproximado de IA hoy: <b>US$ %.2f</b>.</p>') % (
            len(sessions), ', '.join('%s %s' % (n, _SEG.get(k, k)) for k, n in counts.items()),
            len(hot), len(humans), len(matches), cost)
        body = Markup('<div style="font-family:Arial,sans-serif;font-size:14px"><h3>Resumen del asistente web – %s</h3>%s'
                      '<table style="border-collapse:collapse;width:100%%">%s</table>'
                      '<p style="color:#6b7280;font-size:12px">Detalle completo en Asistente web (menú de Odoo). '
                      'Para dejar de recibirlo: parámetro jaguen_website.ai_digest_enabled = 0.</p></div>') % (
            today.strftime('%d/%m/%Y'), summary, rows)
        self.env['mail.mail'].sudo().create({
            'subject': 'Resumen del asistente web – %s (%s conversaciones)' % (today.strftime('%d/%m/%Y'), len(sessions)),
            'body_html': body, 'email_to': to, 'auto_delete': False,
        }).send()
