from odoo import http
from odoo.http import request
from odoo.addons.website.controllers.main import Website


class WebsiteInfoHidden(Website):
    """/website/info lista las aplicaciones instaladas: solo para personal interno."""

    @http.route(sitemap=False)
    def website_info(self, **kwargs):
        if not request.env.user._is_internal():
            raise request.not_found()
        return super().website_info(**kwargs)
