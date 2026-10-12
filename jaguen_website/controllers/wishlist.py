from odoo.http import request, route
from odoo.addons.website_sale_wishlist.controllers.main import WebsiteSaleWishlist


class WebsiteSaleWishlistJaguen(WebsiteSaleWishlist):
    """Los favoritos son de la empresa: cualquier usuario de la empresa puede quitar uno que guardo otro compañero."""

    @route('/shop/wishlist/remove/<int:wish_id>', type='json', auth='public', website=True)
    def remove_from_wishlist(self, wish_id, **kw):
        if request.website.is_public_user():
            return super().remove_from_wishlist(wish_id, **kw)
        Wish = request.env['product.wishlist']
        mine = request.env.user.partner_id.commercial_partner_id
        wish = Wish.sudo().browse(wish_id).exists()
        if wish and wish.partner_id.commercial_partner_id == mine:
            # tambien el mismo producto guardado por otros usuarios de la empresa, para que no "reaparezca"
            wish.search([('partner_id', 'child_of', mine.id), ('product_id', '=', wish.product_id.id)]).unlink()
        return True
