# -*- coding: utf-8 -*-
from odoo import fields, models


class JaguenAlternativeRank(models.Model):
    """Posicion con la que se muestra cada producto alternativo en la ficha del producto.

    El campo "Productos alternativos" de Odoo no guarda orden, y el carrusel de la
    tienda los ordena por nombre. Esta tabla guarda la posicion (1 = primero) para que
    los de alta visibilidad (mismo modelo en otros colores, complementos) salgan primero.
    """
    _name = 'jaguen.alternative.rank'
    _description = 'Orden de productos alternativos en la tienda'
    _order = 'template_id, sequence, id'

    template_id = fields.Many2one('product.template', string='Producto', required=True,
                                  ondelete='cascade', index=True)
    alternative_id = fields.Many2one('product.template', string='Alternativo', required=True,
                                     ondelete='cascade')
    sequence = fields.Integer(string='Posicion', default=10)

    _sql_constraints = [
        ('template_alt_uniq', 'unique(template_id, alternative_id)',
         'Ese alternativo ya tiene posicion para este producto.'),
    ]
