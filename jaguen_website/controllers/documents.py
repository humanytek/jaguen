import base64
import re
from datetime import datetime, time

from odoo import fields, http
from odoo.http import request

TIPOS = [
    'Constancia de Situación Fiscal', 'Opinión de cumplimiento (SAT)', 'INE del representante legal',
    'Comprobante de domicilio', 'Acta constitutiva y poder', 'Estados de cuenta bancarios',
    'Solicitud de crédito (llena y firmada)', 'Documentos para crédito', 'Otro',
]
MAX_MB = 10
MAX_POR_DIA = 20
MAGIC = {'pdf': (b'%PDF',), 'png': (b'\x89PNG',), 'jpg': (b'\xff\xd8\xff',), 'jpeg': (b'\xff\xd8\xff',)}


class PortalDocuments(http.Controller):

    def _company(self):
        return request.env.user.partner_id.commercial_partner_id

    def _docs(self, partner):
        return request.env['ir.attachment'].sudo().search(
            [('res_model', '=', 'res.partner'), ('res_id', '=', partner.id), ('jaguen_portal_visible', '=', True)], order='id desc')

    @http.route('/my/documentos', type='http', auth='user', website=True)
    def my_documents(self, ok=None, error=None, **kw):
        partner = self._company()
        return request.render('jaguen_website.portal_my_documents', {
            'page_name': 'documentos', 'partner': partner, 'docs': self._docs(partner), 'tipos': TIPOS,
            'ok': ok, 'error': error, 'max_mb': MAX_MB,
        })

    @http.route('/my/documentos/subir', type='http', auth='user', methods=['POST'], website=True)
    def my_documents_upload(self, tipo='Otro', **kw):
        partner = self._company()
        file = request.httprequest.files.get('archivo')
        if tipo not in TIPOS:
            tipo = 'Otro'
        if not file or not file.filename:
            return request.redirect('/my/documentos?error=Elige+un+archivo')
        ext = (file.filename.rsplit('.', 1)[-1] if '.' in file.filename else '').lower()
        data = file.read()
        if ext not in MAGIC or not any(data.startswith(m) for m in MAGIC[ext]):
            return request.redirect('/my/documentos?error=Solo+se+aceptan+PDF%2C+JPG+o+PNG')
        if len(data) > MAX_MB * 1024 * 1024:
            return request.redirect('/my/documentos?error=El+archivo+pesa+m%C3%A1s+de+%s+MB' % MAX_MB)
        Att = request.env['ir.attachment'].sudo()
        today = datetime.combine(fields.Date.context_today(Att), time.min)
        if Att.search_count([('res_model', '=', 'res.partner'), ('res_id', '=', partner.id),
                             ('jaguen_portal_visible', '=', True), ('create_date', '>=', today)]) >= MAX_POR_DIA:
            return request.redirect('/my/documentos?error=Alcanzaste+el+l%C3%ADmite+de+archivos+de+hoy')
        safe = re.sub(r'[^\w.\- ]', '_', file.filename)[:80]
        Att.create({'name': '%s - %s' % (tipo, safe), 'description': tipo, 'datas': base64.b64encode(data),
                    'res_model': 'res.partner', 'res_id': partner.id, 'jaguen_portal_visible': True,
                    'mimetype': {'pdf': 'application/pdf', 'png': 'image/png'}.get(ext, 'image/jpeg')})
        if 'rédito' in tipo:
            self._credit_activity(partner)
        return request.redirect('/my/documentos?ok=1')

    def _credit_activity(self, partner):
        """Una sola actividad abierta por empresa para el vendedor cuando suben documentos de credito."""
        summary = 'Documentos de crédito subidos'
        p = partner.sudo()
        if p.activity_ids.filtered(lambda a: a.summary == summary):
            return
        javier = request.env['res.users'].sudo().search([('login', '=', 'ventas.jaguen@hotmail.com')], limit=1)
        user = (p.user_id if p.user_id and p.user_id.active else javier) or request.env.ref('base.user_admin')
        p.with_context(mail_activity_quick_update=True).activity_schedule(
            'mail.mail_activity_data_todo', summary=summary, user_id=user.id,
            note='%s subió documentos para su solicitud de crédito. Revísalos en la ficha de la empresa (Archivos).' % p.name)

    @http.route('/my/documentos/<int:att_id>/descargar', type='http', auth='user', website=True)
    def my_documents_download(self, att_id, **kw):
        partner = self._company()
        att = request.env['ir.attachment'].sudo().browse(att_id).exists()
        if not att or att.res_model != 'res.partner' or att.res_id != partner.id or not att.jaguen_portal_visible:
            raise request.not_found()
        return request.env['ir.binary']._get_stream_from(att).get_response(as_attachment=True)
