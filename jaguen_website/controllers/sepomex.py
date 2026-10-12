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
