import json
import re

from odoo import http
from odoo.http import request


class JaguenSepomexController(http.Controller):

    @http.route('/jaguen/cp/<string:cp>', type='http', auth='public', methods=['GET'], website=True, sitemap=False)
    def cp_lookup(self, cp, **kw):
        headers = [('Content-Type', 'application/json'), ('Cache-Control', 'no-store')]
        if not re.fullmatch(r'\d{5}', cp or ''):
            return request.make_response(json.dumps({}), headers)
        Usage = request.env['jaguen.chat.usage'].sudo()
        key = 'cp:%s' % (request.httprequest.remote_addr or 'sin-ip')
        if Usage._count(key) >= 300:
            return request.make_response(json.dumps({}), headers)
        Usage._bump(key, messages=1)
        return request.make_response(json.dumps(request.env['jaguen.sepomex'].lookup(cp)), headers)


class JaguenCsfController(http.Controller):

    @http.route('/jaguen/csf/check', type='http', auth='public', methods=['POST'], website=True, sitemap=False)
    def csf_check(self, **kw):
        """Revisa (sin guardar nada) la fecha de una CSF recien elegida en Registrate para avisar al cliente al momento."""
        from odoo import fields
        from odoo.addons.jaguen_website.models import csf_parser
        headers = [('Content-Type', 'application/json'), ('Cache-Control', 'no-store')]
        f = request.httprequest.files.get('archivo')
        data = f.read(5 * 1024 * 1024 + 1) if f else b''
        if not data or len(data) > 5 * 1024 * 1024 or not data.startswith(b'%PDF-'):
            return request.make_response(json.dumps({'estado': 'notpdf', 'mensaje': 'Sube un PDF de máximo 5 MB.'}), headers)
        Usage = request.env['jaguen.chat.usage'].sudo()
        key = 'csfchk:%s' % (request.httprequest.remote_addr or 'sin-ip')
        if Usage._count(key) >= 300:
            return request.make_response(json.dumps({'estado': 'unreadable', 'mensaje': ''}), headers)
        Usage._bump(key, messages=1)
        tipo = 'opinion' if kw.get('tipo') == 'opinion' else 'csf'
        texto = csf_parser.pdf_text(data)
        rfc = (kw.get('rfc') or '').strip() or None
        estado, mensaje = csf_parser.revisar_archivo(texto, fields.Date.context_today(Usage), tipo, rfc)
        out = {'estado': estado, 'mensaje': mensaje, 'detalle': csf_parser.detalle(texto, tipo, rfc)}
        if tipo == 'csf' and estado not in ('notcsf', 'notpdf', 'unreadable'):
            out['datos'] = csf_parser.datos_formulario(texto)  # para llenar el formulario (el cliente solo revisa)
        return request.make_response(json.dumps(out), headers)


class JaguenDocsController(http.Controller):

    @http.route('/jaguen/docs/unlocked', type='http', auth='public', methods=['GET'], website=True, sitemap=False)
    def docs_unlocked(self, token='', **kw):
        """Para que el formulario sepa si Ale ya habilito el envio de documentos."""
        from odoo import fields
        headers = [('Content-Type', 'application/json'), ('Cache-Control', 'no-store')]
        Usage = request.env['jaguen.chat.usage'].sudo()
        key = 'docpoll:%s' % (request.httprequest.remote_addr or 'sin-ip')
        if not token or Usage._count(key) >= 600:
            return request.make_response(json.dumps({'unlocked': False, 'level': 0}), headers)
        Usage._bump(key, messages=1)
        sess = request.env['jaguen.chat.session'].sudo().search(
            [('token', '=', token), ('docs_unlocked_until', '>', fields.Datetime.now())], limit=1)
        return request.make_response(json.dumps({'unlocked': bool(sess), 'level': sess.docs_unlock_level if sess else 0}), headers)
