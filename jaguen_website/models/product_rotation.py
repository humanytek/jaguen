# -*- coding: utf-8 -*-
import random
import unicodedata

from odoo import api, fields, models


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
        taken, rows = set(), []
        for _count, top, ids in lines:
            free = [i for i in ids if i not in taken]
            random.shuffle(free)
            peso = 2.0 if 'oficina' in (top.name or '').lower() else 1.0
            for rank, tid in enumerate(free):
                rows.append((rank / peso, tid))
                taken.add(tid)
        for lugar, tid in rows:
            cr.execute("UPDATE product_template SET x_jaguen_portada = %s WHERE id = %s", (lugar, tid))
        self.env.invalidate_all()

    @api.model
    def _jaguen_ordenar_lineas(self):
        """Las lineas salen en la tienda (barra de botones) en el mismo orden que en la pagina principal."""
        orden = ['oficina', 'escolar', 'limpieza', 'empaque', 'computo', 'higiene', 'seguridad',
                 'cafeteria', 'promocional', 'ferreteria', 'varios']
        for categ in self.env['product.public.category'].sudo().search([('parent_id', '=', False)]):
            nombre = unicodedata.normalize('NFD', categ.name or '').encode('ascii', 'ignore').decode().lower()
            for pos, clave in enumerate(orden, start=1):
                if clave in nombre:
                    categ.sequence = pos
                    break
