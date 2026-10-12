import json
import re

from odoo.http import request
from odoo.addons.website.controllers.form import WebsiteForm


class WebsiteFormJaguen(WebsiteForm):
    """Archivos del formulario Registrate: se les pone el tipo en el nombre (CSF, Opinion de cumplimiento) y quedan
    visibles para el cliente en Mi cuenta > Mis documentos."""

    def insert_attachment(self, model, id_record, files):
        for f in files:
            field = (getattr(f, 'field_name', '') or '').lower()
            if 'constancia' in field or 'csf' in field:
                label = 'CSF'
            elif 'opini' in field or 'cumplimiento' in field:
                label = 'Opinión de cumplimiento'
            else:
                label = ''
            if label and not (f.filename or '').startswith(label):
                f.filename = '%s - %s' % (label, f.filename or 'archivo')
        result = super().insert_attachment(model, id_record, files)
        if model.sudo().model == 'res.partner':
            request.env['ir.attachment'].sudo().search(
                [('res_model', '=', 'res.partner'), ('res_id', '=', id_record)]).write({'jaguen_portal_visible': True})
        return result

    def _handle_website_form(self, model_name, **kwargs):
        if model_name == 'res.partner':
            errors = self._jaguen_check_registration(kwargs)
            if errors:
                return json.dumps({'error_fields': list(errors)})
        return super()._handle_website_form(model_name, **kwargs)

    def _jaguen_check_registration(self, kw):
        """Validacion en el servidor del Registrate (la del navegador se puede saltar con un POST directo) y tope
        diario por IP / global para que un bot no llene de empresas ni de avisos a ventas."""
        errors = {}
        mail_re = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
        if len((kw.get('name') or '').strip()) < 2:
            errors['name'] = 'required'
        if not mail_re.match((kw.get('email') or '').strip()):
            errors['email'] = 'invalid'
        if len((kw.get('jaguen_contact_name') or '').strip()) < 2:
            errors['jaguen_contact_name'] = 'required'
        if not mail_re.match((kw.get('jaguen_contact_email') or '').strip()):
            errors['jaguen_contact_email'] = 'invalid'
        for key in ('name', 'jaguen_contact_name', 'jaguen_ship_receiver', 'jaguen_ship_street'):
            if len(kw.get(key) or '') > 150:
                errors[key] = 'invalid'
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
