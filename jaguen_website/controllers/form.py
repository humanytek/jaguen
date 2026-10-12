import json
import logging
import re

from odoo.http import request
from odoo.addons.website.controllers.form import WebsiteForm

_logger = logging.getLogger(__name__)


class WebsiteFormJaguen(WebsiteForm):
    """Archivos del formulario Registrate: se les pone el tipo en el nombre (CSF, Opinion de cumplimiento) y quedan
    visibles para el cliente en Mi cuenta > Mis documentos."""

    def insert_attachment(self, model, id_record, files):
        """Los archivos se guardan como "CSF - Cliente.pdf" y "Opinion - Cliente.pdf"."""
        client = ''
        if model.sudo().model == 'res.partner':
            client = re.sub(r'[\\/:*?"<>|]', ' ', request.env['res.partner'].sudo().browse(id_record).name or '').strip()[:80]
        for f in files:
            field = (getattr(f, 'field_name', '') or '').lower()
            if 'constancia' in field or 'csf' in field:
                label = 'CSF'
            elif 'opini' in field or 'cumplimiento' in field:
                label = 'Opinion'
            else:
                label = ''
            if label:
                ext = (f.filename or '').rsplit('.', 1)[-1].lower() if '.' in (f.filename or '') else 'pdf'
                f.filename = '%s - %s.%s' % (label, client or 'cliente', ext)
        result = super().insert_attachment(model, id_record, files)
        if model.sudo().model == 'res.partner':
            request.env['ir.attachment'].sudo().search(
                [('res_model', '=', 'res.partner'), ('res_id', '=', id_record)]).write({'jaguen_portal_visible': True})
        return result

    def _handle_website_form(self, model_name, **kwargs):
        if model_name == 'res.partner':
            dup = self._jaguen_duplicate_message(kwargs)
            if dup:
                return json.dumps({'error': dup})
            errors = self._jaguen_check_registration(kwargs)
            if errors:
                return json.dumps({'error_fields': list(errors)})
        result = super()._handle_website_form(model_name, **kwargs)
        if model_name == 'res.partner':
            try:
                rec_id = json.loads(result).get('id')
                partner = request.env['res.partner'].sudo().browse(rec_id).exists() if rec_id else None
                if partner and partner.jaguen_alta_hold:
                    unlocked = self._jaguen_unlocked_session()
                    partner._jaguen_finish_registration(forced=unlocked.docs_unlock_note if unlocked else None)
            except Exception:
                _logger.exception('Registrate: no se pudo cerrar el alta')
        return result

    @staticmethod
    def _jaguen_file(field):
        """El formulario de Odoo manda los archivos como 'Nombre del campo[0][0]': se busca por el prefijo."""
        files = request.httprequest.files
        if field in files:
            return files[field]
        for key in files:
            if key.startswith(field + '['):
                return files[key]
        return None

    def _jaguen_duplicate_message(self, kw):
        """Evita duplicados: doble clic en Enviar o un cliente que ya existe (mismo RFC) registrandose otra vez.
        No deja nota interna ni avisa a nadie (es silencioso para nosotros, solo le contesta al que esta en la
        pagina). Tope de 2 "ya existe" por IP al dia para que no se use para adivinar que RFC son clientes nuestros;
        pasado el tope, un mensaje neutro que ni confirma ni niega."""
        from datetime import timedelta
        from odoo import fields
        Partner = request.env['res.partner'].sudo()
        Usage = request.env['jaguen.chat.usage'].sudo()
        personal = str(kw.get('jaguen_personal') or '').lower() in ('1', 'true', 'on', 'yes', 'si', 'sí')
        login_msg = 'Este RFC ya está registrado en Jaguen. Intenta recuperar tu contraseña aquí: /web/reset_password'
        neutral_msg = 'No se pudo completar tu registro en este momento. Si ya tienes cuenta, entra a Mi cuenta o escríbenos a contacto.jaguen@gmail.com.'
        rfc = re.sub(r'[\s-]', '', (kw.get('vat') or '').upper())
        if rfc.startswith('MX') and len(rfc) > 13:
            rfc = rfc[2:]
        email = (kw.get('email') or '').strip()
        recent = fields.Datetime.now() - timedelta(minutes=15)
        if not personal and rfc and rfc not in ('XAXX010101000', 'XEXX010101000'):
            found = Partner.search([('parent_id', '=', False), ('vat', 'in', [rfc, 'MX' + rfc])], limit=1)
            if found:
                if found.create_date and found.create_date > recent and email and (found.email or '').lower() == email.lower():
                    return 'Ya recibimos tu registro. En horario laboral un asesor se comunica contigo.'
                ip_key = 'rfcdup:%s' % (request.httprequest.remote_addr or 'sin-ip')
                if Usage._count(ip_key) >= 2:
                    return neutral_msg
                Usage._bump(ip_key, messages=1)
                return login_msg
        elif personal and email:
            found = Partner.search([('parent_id', '=', False), ('email', '=ilike', email), ('create_date', '>', recent)], limit=1)
            if found:
                return 'Ya recibimos tu registro. En horario laboral un asesor se comunica contigo.'
        return ''

    def _jaguen_unlocked_session(self):
        """Sesion de chat (cookie jg_chat) a la que Ale le habilito el envio de documentos, o vacio."""
        token = request.httprequest.cookies.get('jg_chat')
        if not token:
            return request.env['jaguen.chat.session']
        from odoo import fields
        return request.env['jaguen.chat.session'].sudo().search(
            [('token', '=', token), ('docs_unlocked_until', '>', fields.Datetime.now()), ('docs_unlock_level', '>=', 1)], limit=1)

    def _jaguen_check_registration(self, kw):
        """Validacion en el servidor del Registrate (la del navegador se puede saltar con un POST directo) y tope
        diario por IP / global para que un bot no llene de empresas ni de avisos a ventas."""
        errors = {}
        mail_re = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
        personal = str(kw.get('jaguen_personal') or '').lower() in ('1', 'true', 'on', 'yes', 'si', 'sí')
        if len((kw.get('name') or '').strip()) < 2:
            errors['name'] = 'required'
        if not mail_re.match((kw.get('email') or '').strip()):
            errors['email'] = 'invalid'
        if not personal and not re.match(r'^(MX)?[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$', re.sub(r'[\s-]', '', (kw.get('vat') or '').upper())):
            errors['vat'] = 'invalid'
        if not personal and len((kw.get('jaguen_contact_name') or '').strip()) < 2:
            errors['jaguen_contact_name'] = 'required'
        if not personal and not mail_re.match((kw.get('jaguen_contact_email') or '').strip()):
            errors['jaguen_contact_email'] = 'invalid'
        for key in ('name', 'jaguen_contact_name', 'jaguen_ship_receiver', 'jaguen_ship_street'):
            if len(kw.get(key) or '') > 150:
                errors[key] = 'invalid'
        unlocked = self._jaguen_unlocked_session()
        level = unlocked.docs_unlock_level if unlocked else 0
        rfcs = {}
        for field in (() if personal else ('Constancia Situación Fiscal', 'Opinión de cumplimiento')):
            f = self._jaguen_file(field)
            if not f or not (f.filename or '').strip():
                # La CSF siempre es obligatoria; con el desbloqueo de Ale solo la opinion deja de serlo.
                if level < 1 or field.startswith('Constancia'):
                    errors[field] = 'required'
                continue
            f.seek(0, 2)
            size = f.tell()
            f.seek(0)
            if size > 5 * 1024 * 1024:
                errors[field] = 'invalid'
                continue
            head = f.read(5)
            f.seek(0)
            is_pdf = (f.filename or '').lower().endswith('.pdf') and head == b'%PDF-'
            is_img = head[:3] == b'\xff\xd8\xff' or head[:4] == b'\x89PNG'
            if field.startswith('Constancia') and level >= 1 and is_img and (f.filename or '').lower().endswith(('.jpg', '.jpeg', '.png')):
                continue  # con el desbloqueo de Ale la CSF puede ir como foto (queda marcada para revision)
            if not is_pdf:
                errors[field] = 'invalid'
                continue
            from odoo import fields
            from ..models import csf_parser
            tipo = 'csf' if field.startswith('Constancia') else 'opinion'
            texto = csf_parser.pdf_text(f.read(5 * 1024 * 1024 + 1))
            f.seek(0)
            estado, _msg = csf_parser.revisar_archivo(
                texto, fields.Date.context_today(request.env['res.partner']), tipo, kw.get('vat'))
            # Con el envio desbloqueado por Ale solo sigue bloqueando que el RFC no sea el mismo.
            if estado == 'rfcdiff' or (estado in ('old', 'future', 'notcsf') and level < 1):
                errors[field] = 'invalid'
            rfcs[tipo] = csf_parser.rfc_del_archivo(texto, tipo)
        if rfcs.get('csf') and rfcs.get('opinion'):
            from ..models import csf_parser
            if not csf_parser.mismo_rfc(rfcs['csf'], rfcs['opinion']):
                errors['Opinión de cumplimiento'] = 'invalid'
        if errors:
            return errors
        Usage = request.env['jaguen.chat.usage'].sudo()
        Param = request.env['ir.config_parameter'].sudo()
        ip_key = 'reg:%s' % (request.httprequest.remote_addr or 'sin-ip')
        if Usage._count(ip_key) >= int(Param.get_param('jaguen_website.reg_daily_ip', 10)) or \
                Usage._count('reg:global') >= int(Param.get_param('jaguen_website.reg_daily_global', 60)):
            return {'name': 'invalid'}
        Usage._bump(ip_key, messages=1)
        Usage._bump('reg:global', messages=1)
        return {}
