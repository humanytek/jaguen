# -*- coding: utf-8 -*-
import random
import unicodedata

from odoo import api, fields, models


ORDEN_LINEAS = ['oficina', 'escolar', 'limpieza', 'empaque', 'computo', 'higiene', 'seguridad',
                'cafeteria', 'promocional', 'ferreteria', 'varios']


class ProductTemplateRotation(models.Model):
    _inherit = 'product.template'

    x_jaguen_rotacion = fields.Integer(
        string='Orden de rotación diaria (tienda)', index=True, copy=False,
        default=lambda self: random.randint(0, 999999),
        help='Número al azar que cambia una vez al día. Sirve para que los productos de la tienda '
             'no salgan siempre en el mismo orden cuando el cliente no escoge otro orden.')
    x_jaguen_portada = fields.Float(
        string='Lugar en la portada de la tienda (rotación diaria)', index=True, copy=False, default=9999.0,
        help='Se recalcula cada noche: ordena la primera página de /shop para que salgan 2 productos de '
             'Papelería Oficina y 1 de cada una de las otras líneas, distintos cada día.')

    @api.model
    def _jaguen_posicion_linea(self, nombre):
        """Lugar de la linea en la pagina principal (1 = Papeleria Oficina ... 11 = Productos Varios); 0 si no se reconoce."""
        n = unicodedata.normalize('NFD', nombre or '').encode('ascii', 'ignore').decode().lower()
        for pos, clave in enumerate(ORDEN_LINEAS, start=1):
            if clave in n:
                return pos
        return 0

    @api.model
    def _jaguen_rotar_catalogo(self):
        """Revuelve el orden de la tienda (una vez al dia, por tarea programada). No toca el orden
        manual 'website_sequence': solo cambia estos numeros al azar."""
        cr = self.env.cr
        cr.execute("UPDATE product_template SET x_jaguen_rotacion = floor(random() * 1000000)::int, x_jaguen_portada = 9999")
        Categ = self.env['product.public.category'].sudo()
        Tmpl = self.sudo()
        tops = Categ.search([('parent_id', '=', False)])
        lines = []
        for top in tops:
            ids = Tmpl.search([('public_categ_ids', 'child_of', top.id), ('is_published', '=', True), ('sale_ok', '=', True)]).ids
            lines.append((len(ids), top, ids))
        # Las lineas mas chicas escogen primero, para que un producto que esta en varias lineas no deje vacia a la chica.
        lines.sort(key=lambda x: x[0])
        # Cada "bloque" son 12 lugares: 2 de Papeleria Oficina y 1 de cada otra linea, en el orden de la pagina
        # principal (Oficina, Oficina, Escolar, Limpieza, Empaque, Computo, Higiene, Seguridad, Cafeteria,
        # Promocionales, Ferreteria, Varios). Dentro de cada linea el producto que toca va al azar.
        taken, rows = set(), []
        for _count, top, ids in lines:
            free = [i for i in ids if i not in taken]
            random.shuffle(free)
            pos = self._jaguen_posicion_linea(top.name) or 11.5
            for rank, tid in enumerate(free):
                if pos == 1:
                    lugar = (rank // 2) * 12 + (rank % 2)
                else:
                    lugar = rank * 12 + pos
                rows.append((lugar, tid))
                taken.add(tid)
        for lugar, tid in rows:
            cr.execute("UPDATE product_template SET x_jaguen_portada = %s WHERE id = %s", (lugar, tid))
        self.env.invalidate_all()

    @api.model
    def _jaguen_ordenar_lineas(self):
        """Las lineas salen en la tienda (barra de botones) en el mismo orden que en la pagina principal."""
        for categ in self.env['product.public.category'].sudo().search([('parent_id', '=', False)]):
            pos = self._jaguen_posicion_linea(categ.name)
            if pos:
                categ.sequence = pos
