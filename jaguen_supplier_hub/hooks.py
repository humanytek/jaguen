from odoo import SUPERUSER_ID, api  # noqa: F401  (api se deja por compatibilidad con otras versiones)


def post_init_hook(env):
    """Liga cada proveedor de ApiHub con su proveedor de Odoo buscando por parte del nombre."""
    for provider in env["apihub.provider"].search([("partner_id", "=", False), ("partner_pattern", "!=", False)]):
        partner = env["res.partner"].search([("name", "ilike", provider.partner_pattern)], limit=1)
        if partner:
            provider.partner_id = partner
