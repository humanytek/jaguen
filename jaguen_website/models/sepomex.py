import csv
import gzip
import hashlib
import io
import unicodedata

from odoo import api, fields, models
from odoo.tools import file_path

# c_estado de SEPOMEX -> codigo del estado en Odoo
STATE_CODE = {
    '01': 'AGU', '02': 'BCN', '03': 'BCS', '04': 'CAM', '05': 'COA', '06': 'COL', '07': 'CHP', '08': 'CHH',
    '09': 'CMX', '10': 'DUR', '11': 'GUA', '12': 'GRO', '13': 'HID', '14': 'JAL', '15': 'MEX', '16': 'MIC',
    '17': 'MOR', '18': 'NAY', '19': 'NLE', '20': 'OAX', '21': 'PUE', '22': 'QUE', '23': 'ROO', '24': 'SLP',
    '25': 'SIN', '26': 'SON', '27': 'TAB', '28': 'TAM', '29': 'TLA', '30': 'VER', '31': 'YUC', '32': 'ZAC',
}


def _norm(txt):
    txt = unicodedata.normalize('NFKD', txt or '')
    return ''.join(c for c in txt if not unicodedata.combining(c)).lower().strip()


class JaguenSepomex(models.Model):
    """Catalogo de Codigos Postales de Correos de Mexico (SEPOMEX), solo para autocompletar el Registrate."""
    _name = 'jaguen.sepomex'
    _description = 'Codigos postales SEPOMEX'
    _order = 'cp, colonia'

    cp = fields.Char(required=True, index=True)
    colonia = fields.Char(required=True)
    tipo = fields.Char()
    municipio = fields.Char()
    ciudad = fields.Char()
    c_estado = fields.Char()

    @api.model
    def _load_file(self):
        """Carga data/sepomex.csv.gz una sola vez (o cuando cambia el archivo). Seguro de correr en cada actualizacion."""
        try:
            path = file_path('jaguen_website/data/sepomex.csv.gz')
        except FileNotFoundError:
            return
        with open(path, 'rb') as f:
            raw = f.read()
        digest = hashlib.sha1(raw).hexdigest()
        Param = self.env['ir.config_parameter'].sudo()
        if Param.get_param('jaguen_website.sepomex_hash') == digest and self.search_count([]):
            return
        rows = list(csv.reader(io.StringIO(gzip.decompress(raw).decode('utf-8'))))
        cr = self.env.cr
        cr.execute('DELETE FROM jaguen_sepomex')
        for i in range(0, len(rows), 5000):
            chunk = rows[i:i + 5000]
            args = b','.join(cr.mogrify('(%s,%s,%s,%s,%s,%s)', r) for r in chunk)
            cr.execute(b'INSERT INTO jaguen_sepomex (cp, colonia, tipo, municipio, ciudad, c_estado) VALUES ' + args)
        Param.set_param('jaguen_website.sepomex_hash', digest)
        self.env.registry.clear_cache()

    @api.model
    def lookup(self, cp):
        """Devuelve colonias y los ids de estado / ciudad / localidad de Odoo para un CP, o {} si no existe."""
        recs = self.sudo().search([('cp', '=', cp)])
        if not recs:
            return {}
        first = recs[0]
        env = self.env
        state = env['res.country.state'].sudo().search(
            [('country_id.code', '=', 'MX'), ('code', '=', STATE_CODE.get(first.c_estado))], limit=1)
        city = loc = env['res.city']
        if state:
            wanted = {_norm(first.municipio), _norm(first.ciudad)} - {''}
            city = next((c for c in env['res.city'].sudo().search([('state_id', '=', state.id)])
                         if _norm(c.name) in wanted), env['res.city'])
            loc = next((c for c in env['l10n_mx_edi.res.locality'].sudo().search([('state_id', '=', state.id)])
                        if _norm(c.name) in wanted), env['l10n_mx_edi.res.locality'])
        return {
            'estado_id': state.id or 0, 'estado': state.name or '',
            'ciudad_id': city.id or 0, 'localidad_id': loc.id or 0,
            'municipio': first.municipio, 'ciudad': first.ciudad or first.municipio,
            'colonias': [{'n': r.colonia, 't': r.tipo or ''} for r in recs],
        }
