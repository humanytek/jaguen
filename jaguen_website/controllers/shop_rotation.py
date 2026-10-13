# -*- coding: utf-8 -*-
import re

from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale

_SHOP_ROOT = re.compile(r'(^|/)shop(/page/\d+)?/?$')


class WebsiteSaleRotation(WebsiteSale):

    def _get_search_order(self, post):
        """Sin orden escogido y sin busqueda, la tienda muestra los productos en el orden del dia
        (cambia al azar una vez al dia). En la portada (/shop sin filtros) salen 2 de Papeleria
        Oficina y 1 de cada otra linea. Si el cliente ordena (precio, nombre...) o busca algo, se
        respeta tal cual."""
        if not post.get('order') and not request.params.get('search'):
            if _SHOP_ROOT.search(request.httprequest.path) and not request.httprequest.args:
                return 'is_published desc, x_jaguen_portada asc, x_jaguen_rotacion asc, id desc'
            return 'is_published desc, x_jaguen_rotacion asc, id desc'
        return super()._get_search_order(post)
