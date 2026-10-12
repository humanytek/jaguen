from odoo.http import request
from odoo.addons.website.controllers.form import WebsiteForm


class WebsiteFormJaguen(WebsiteForm):
    """Archivos del formulario Registrate: se les pone el tipo en el nombre (CSF, Opinion de cumplimiento) y quedan
    visibles para el cliente en Mi cuenta > Mis documentos."""

    def insert_attachment(self, model, id_record, files):
        for f in files:
            field = (getattr(f, 'field_name', '') or '').lower()
            if 'constancia' in field or 'csf' in field:
                label = 'CSF'
            elif 'opini' in field or 'cumplimiento' in field:
                label = 'Opinión de cumplimiento'
            else:
                label = ''
            if label and not (f.filename or '').startswith(label):
                f.filename = '%s - %s' % (label, f.filename or 'archivo')
        result = super().insert_attachment(model, id_record, files)
        if model.sudo().model == 'res.partner':
            request.env['ir.attachment'].sudo().search(
                [('res_model', '=', 'res.partner'), ('res_id', '=', id_record)]).write({'jaguen_portal_visible': True})
        return result
