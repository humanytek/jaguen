# -*- coding: utf-8 -*-
from odoo import fields, http
from odoo.http import request


class JaguenNovedades(http.Controller):

    @http.route('/jaguen/novedad/visto', type='json', auth='user', website=True)
    def novedad_visto(self, page=None, **kw):
        """La persona ya vio la novedad de esa pagina: se apaga su aviso 'Nuevo'."""
        if page != 'puntos':
            return False
        request.env.user.partner_id.sudo().write({'jg_novedad_%s_visto' % page: fields.Datetime.now()})
        return True
