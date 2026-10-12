from odoo import api, models
from odoo.http import request


class ProductWishlist(models.Model):
    """Favoritos compartidos por empresa: lo que guarda un usuario de la empresa lo ven todos los de esa empresa.
    Tambien permite que el equipo agregue favoritos a un cliente a mano (linea por linea o importando)."""
    _inherit = 'product.wishlist'

    @api.model
    def _jaguen_company_partners(self, partner):
        return self.env['res.partner'].sudo().search([('id', 'child_of', partner.commercial_partner_id.id)])

    @api.model
    def current(self):
        if not request or request.website.is_public_user():
            return super().current()
        partners = self._jaguen_company_partners(self.env.user.partner_id)
        wish = self.sudo().search([('partner_id', 'in', partners.ids), ('website_id', '=', request.website.id)])
        seen, keep = set(), self.sudo()
        for w in wish.sorted('id'):
            if w.product_id.id in seen:
                continue
            seen.add(w.product_id.id)
            keep |= w
        return keep.filtered(
            lambda w: w.product_id.product_tmpl_id.website_published
            and w.product_id.product_tmpl_id._can_be_added_to_cart())

    @api.model_create_multi
    def create(self, vals_list):
        """Si alguien de la empresa ya tiene el producto en favoritos no se duplica; y al crear desde el backend
        se completan sitio web, precio y moneda."""
        website = self.env['website'].sudo().search([], limit=1)
        result = self.browse()
        for vals in vals_list:
            product = self.env['product.product'].browse(vals.get('product_id'))
            partner = self.env['res.partner'].browse(vals.get('partner_id')) if vals.get('partner_id') else None
            if partner and product:
                partners = self._jaguen_company_partners(partner)
                found = self.sudo().with_context(active_test=False).search(
                    [('partner_id', 'in', partners.ids), ('product_id', '=', product.id)], limit=1)
                if found:
                    if not found.active:
                        found.active = True
                    result |= found
                    continue
            vals = dict(vals)
            vals.setdefault('website_id', website.id)
            if 'price' not in vals and product:
                vals['price'] = product.sudo().lst_price
            result |= super().create([vals])
        return result
