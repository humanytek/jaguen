# -*- coding: utf-8 -*-
import re

from odoo import http, fields, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal


class JaguenLoyaltyPortal(CustomerPortal):

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _jaguen_get_partner_ids(self):
        """IDs de partner a considerar para buscar tarjetas: el contacto que
        inició sesión y, si aplica, la empresa comercial a la que pertenece
        (los puntos de compra de una empresa suelen acumularse en el
        partner comercial, no en cada contacto individual)."""
        partner = request.env.user.partner_id
        commercial_partner = partner.commercial_partner_id
        partner_ids = {partner.id}
        if commercial_partner:
            partner_ids.add(commercial_partner.id)
            # Odoo crea una tarjeta aparte por cada contacto a cuyo nombre
            # se hace un pedido (p. ej. una sucursal hija de la empresa).
            # Los puntos son de la empresa, asi que se consideran tambien
            # las tarjetas de todos sus contactos.
            partner_ids.update(
                request.env['res.partner'].sudo().with_context(active_test=False).search([
                    ('commercial_partner_id', '=', commercial_partner.id),
                ]).ids
            )
        return list(partner_ids)

    def _jaguen_get_commercial_partner(self):
        partner = request.env.user.partner_id
        return partner.commercial_partner_id or partner

    def _jaguen_terminos_pendientes(self):
        """True si este cliente todavia no contesta la pantalla de
        Terminos y Condiciones de 'Mis Puntos' (las 2 casillas)."""
        partner = self._jaguen_get_commercial_partner()
        return not partner.sudo().x_terminos_portal_respondido

    def _jaguen_reward_label(self, reward):
        """Texto amigable de qué gana el cliente en este tramo, calculado a
        partir de los campos reales de la recompensa (no se usa el campo
        'description' nativo porque puede quedar desactualizado si el tipo
        de recompensa se edita después de creada)."""
        reward = reward.sudo()
        if reward.x_jaguen_reward_audience:
            # Tramos de Rebate Anual (NC / tarjeta de regalo): son de
            # referencia, no un descuento real calculado por Odoo, así que
            # se usa el texto que ya trae la descripción en vez del % crudo.
            return reward.description or _('Recompensa')
        if reward.reward_type == 'product':
            if reward.multi_product and reward.reward_product_ids:
                names = ' o '.join(n.split(' - ', 1)[-1] for n in reward.reward_product_ids.mapped('name'))
                return _('Escoge: %s') % names
            product = reward.reward_product_id
            if product:
                qty = reward.reward_product_qty or 1
                if qty > 1:
                    return '%s x %s' % (int(qty), product.name)
                return product.name
            return _('Producto de regalo')
        if reward.reward_type == 'discount':
            if reward.discount_mode == 'percent':
                return _('%s%% de descuento') % reward.discount
            if reward.discount_mode == 'per_point':
                return _('$%s de descuento por punto') % '{:,.2f}'.format(reward.discount)
            if reward.program_id.x_jaguen_loyalty_group == 'pedido_linea':
                return _('$%s en Vale de Gasolina') % '{:.2f}'.format(reward.discount)
            return _('$%s de descuento') % '{:,.2f}'.format(reward.discount)
        if reward.reward_type == 'shipping':
            return _('Envío gratis')
        return reward.description or _('Recompensa')

    def _jaguen_get_reward_image_url(self, reward):
        reward = reward.sudo()
        if reward.reward_type == 'product' and not reward.multi_product and reward.reward_product_id:
            return '/my/loyalty/reward_image/%s' % reward.id
        return False

    # -- Grupo "Programa de Recompensa" (JAGUEN Starter u. Rebate Anual) ---
    def _jaguen_get_recompensa_program(self):
        """Cuál de los dos programas de recompensa aplica hoy: mientras el
        cliente no tenga 'Objetivo del año' capturado está en onboarding
        (JAGUEN Starter); en cuanto se le captura, pasa a Rebate Anual. Nunca
        se muestran los dos a la vez.

        Cada uno tiene ademas su propio candado de aceptacion: JAGUEN Starter
        depende de 'Incentivos Starter' (es 100% regalos al comprador);
        Rebate Anual depende de 'acepta rebate anual' (la nota de credito a
        la empresa no es un Incentivo Starter, pero el cliente puede no
        querer ni ese esquema)."""
        partner = self._jaguen_get_commercial_partner()
        if partner.x_objetivo_anual_programa2:
            if not partner.x_acepta_rebate_anual:
                return request.env['loyalty.program']
            group = 'rebate'
        else:
            if not partner.x_acepta_incentivos_personales:
                return request.env['loyalty.program']
            group = 'onboarding'
        return request.env['loyalty.program'].sudo().search([
            ('portal_visible', '=', True),
            ('x_jaguen_loyalty_group', '=', group),
        ], limit=1)

    def _jaguen_get_program_data(self, program):
        """Puntos, barra de progreso y escalera de tramos para UN programa
        acumulativo (JAGUEN Starter / Rebate Anual).

        En Rebate Anual, un mismo nivel reparte dos cosas (nota de credito
        a la empresa + tarjeta de regalo al comprador, marcadas con
        x_jaguen_reward_audience). El tramo 'comprador' se oculta si este
        cliente no acepto Incentivos Starter, aunque si haya aceptado
        participar en Rebate Anual en si.

        Rebate Anual es meta INDIVIDUAL por cliente (x_objetivo_anual_
        programa2), pero required_points de loyalty.reward es un valor
        fijo a nivel de programa (compartido por todos los clientes) --
        Odoo no permite que varie por cliente. Por eso, solo para este
        programa, se ignora el required_points del dato maestro y se usa
        el objetivo capturado en la ficha del cliente como umbral
        efectivo de cada tramo."""
        if not program:
            return False
        partner = self._jaguen_get_commercial_partner()
        partner_ids = self._jaguen_get_partner_ids()
        Card = request.env['loyalty.card'].sudo()
        cards = Card.search([
            ('program_id', '=', program.id),
            ('partner_id', 'in', partner_ids),
        ])
        points = sum(cards.mapped('points'))
        points_pending = sum(cards.mapped('x_puntos_pendientes'))
        point_name = program.portal_point_name or _('puntos')

        is_rebate = program.x_jaguen_loyalty_group == 'rebate'
        objetivo_individual = partner.x_objetivo_anual_programa2 if is_rebate else 0.0

        rewards = program.reward_ids.sudo().filtered(
            lambda r: r.required_points > 0
            and (
                r.x_jaguen_reward_audience != 'comprador'
                or partner.x_acepta_incentivos_personales
            )
        ).sorted(key=lambda r: r.required_points)

        def _umbral(reward):
            """required_points efectivo de este tramo: el objetivo
            individual del cliente en Rebate Anual, o el valor del dato
            maestro para el resto de los programas."""
            return objetivo_individual if is_rebate and objetivo_individual else reward.required_points

        tiers = []
        next_reward = None
        for reward in rewards:
            umbral = _umbral(reward)
            unlocked = points >= umbral
            if not unlocked and next_reward is None:
                next_reward = reward
            tiers.append({
                'reward': reward,
                'unlocked': unlocked,
                'label': self._jaguen_reward_label(reward),
                'image_url': self._jaguen_get_reward_image_url(reward),
                'required_points': umbral,
            })

        max_points = _umbral(rewards[-1]) if rewards else 0.0
        progress_pct = round(min(100.0, (points / max_points * 100.0)), 1) if max_points else 0.0
        missing_points = max(0.0, (_umbral(next_reward) - points)) if next_reward else 0.0

        return {
            'program': program,
            'points': points,
            'points_pending': points_pending,
            'point_name': point_name,
            'tiers': tiers,
            'next_reward': next_reward,
            'next_reward_label': self._jaguen_reward_label(next_reward) if next_reward else False,
            'missing_points': missing_points,
            'progress_pct': progress_pct,
            'max_points': max_points,
            'all_unlocked': bool(rewards) and next_reward is None,
        }

    # -- Grupos "Mi Primer Pedido de $X" / "...por Línea" ----------------
    def _jaguen_group_item_label(self, program):
        """Etiqueta corta para un ítem de checklist, a partir del nombre
        del programa (le quita el prefijo numerado y el texto repetido)."""
        name = program.name or ''
        name = re.sub(r'^\d\)\s*', '', name)
        name = re.sub(r'^Mi Primer Pedido de\s*', '', name)
        name = re.sub(r'^Mi Primer Pedido \$[\d,]+\s*por Línea\s*-\s*', '', name)
        return name.strip() or name

    def _jaguen_get_checklist_data(self, group):
        """Para 'pedido_monto' y 'pedido_linea': cada programa del grupo es
        un tramo independiente (no acumulable entre sí), así que se muestra
        como 'Hecho' / 'Pendiente' en vez de una barra de progreso.

        Los dos son 100% Incentivos Starter (regalos promocionales
        y vales de gasolina, segun el tramo), asi que si el cliente no
        los acepto, el grupo entero queda vacio y su boton desaparece de
        la pantalla principal."""
        partner = self._jaguen_get_commercial_partner()
        if not partner.x_acepta_incentivos_personales:
            return {'items': [], 'done_count': 0, 'total_count': 0}

        partner_ids = self._jaguen_get_partner_ids()
        Card = request.env['loyalty.card'].sudo()
        programs = request.env['loyalty.program'].sudo().search([
            ('portal_visible', '=', True),
            ('x_jaguen_loyalty_group', '=', group),
        ], order='id')

        items = []
        for program in programs:
            cards = Card.search([
                ('program_id', '=', program.id),
                ('partner_id', 'in', partner_ids),
            ])
            done = any(c.points > 0 for c in cards)
            pending_payment = bool(cards and not done and any(c.x_puntos_pendientes > 0 for c in cards))
            reward = program.reward_ids.sudo()[:1]
            items.append({
                'program': program,
                'label': self._jaguen_group_item_label(program),
                'reward_label': self._jaguen_reward_label(reward) if reward else False,
                'done': done,
                'pending_payment': pending_payment,
            })

        done_count = sum(1 for item in items if item['done'])
        return {
            'items': items,
            'done_count': done_count,
            'total_count': len(items),
        }

    # -- Pantalla principal: 3 botones ------------------------------------
    def _jaguen_get_landing_data(self):
        recompensa_program = self._jaguen_get_recompensa_program()
        return {
            'recompensa': self._jaguen_get_program_data(recompensa_program),
            'monto': self._jaguen_get_checklist_data('pedido_monto'),
            'linea': self._jaguen_get_checklist_data('pedido_linea'),
        }

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------
    @http.route(['/my/loyalty/terminos'], type='http', auth='user', website=True)
    def jaguen_my_loyalty_terminos(self, **kw):
        partner = self._jaguen_get_commercial_partner()
        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'loyalty',
            'partner': partner,
        })
        return request.render('jaguen_loyalty_portal.portal_my_loyalty_terminos', values)

    @http.route(['/my/loyalty/terminos/completos'], type='http', auth='user', website=True)
    def jaguen_my_loyalty_terminos_completos(self, **kw):
        values = self._prepare_portal_layout_values()
        values.update({'page_name': 'loyalty'})
        return request.render('jaguen_loyalty_portal.portal_my_loyalty_terminos_completos', values)

    @http.route(['/my/loyalty/terminos/guardar'], type='http', auth='user', website=True, methods=['POST'])
    def jaguen_my_loyalty_terminos_guardar(self, **post):
        partner = self._jaguen_get_commercial_partner()
        partner.sudo().write({
            'x_terminos_portal_respondido': True,
            'x_terminos_portal_fecha': fields.Datetime.now(),
            'x_acepta_incentivos_personales': bool(post.get('acepta_personales')),
            'x_acepta_rebate_anual': bool(post.get('acepta_rebate')),
        })
        return request.redirect('/my/loyalty')

    @http.route(['/my/loyalty'], type='http', auth='user', website=True)
    def jaguen_my_loyalty(self, **kw):
        if self._jaguen_terminos_pendientes():
            return request.redirect('/my/loyalty/terminos')
        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'loyalty',
            'landing': self._jaguen_get_landing_data(),
        })
        return request.render('jaguen_loyalty_portal.portal_my_loyalty', values)

    @http.route(['/my/loyalty/recompensa'], type='http', auth='user', website=True)
    def jaguen_my_loyalty_recompensa(self, **kw):
        if self._jaguen_terminos_pendientes():
            return request.redirect('/my/loyalty/terminos')
        program = self._jaguen_get_recompensa_program()
        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'loyalty',
            'pdata': self._jaguen_get_program_data(program),
        })
        return request.render('jaguen_loyalty_portal.portal_my_loyalty_recompensa', values)

    @http.route(['/my/loyalty/pedido-monto'], type='http', auth='user', website=True)
    def jaguen_my_loyalty_monto(self, **kw):
        if self._jaguen_terminos_pendientes():
            return request.redirect('/my/loyalty/terminos')
        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'loyalty',
            'page_title': _('Mi Primer Pedido de $X'),
            'page_subtitle': _(
                'No tiene que ser literalmente tu primer pedido: es la '
                'primera vez que uno de tus pedidos alcance cada uno de '
                'estos montos. Cada tramo se desbloquea una sola vez. En cada pedido '
                'se desbloquea únicamente el tramo más alto que alcances y que aún '
                'no tengas; los demás se desbloquean en tus siguientes pedidos.'
            ),
            'back_url': '/my/loyalty',
            'checklist': self._jaguen_get_checklist_data('pedido_monto'),
        })
        return request.render('jaguen_loyalty_portal.portal_my_loyalty_checklist', values)

    @http.route(['/my/loyalty/pedido-linea'], type='http', auth='user', website=True)
    def jaguen_my_loyalty_linea(self, **kw):
        if self._jaguen_terminos_pendientes():
            return request.redirect('/my/loyalty/terminos')
        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'loyalty',
            'page_title': _('Mi Primer Pedido por Línea'),
            'page_subtitle': _(
                'No tiene que ser literalmente tu primer pedido: es la '
                'primera vez que uno de tus pedidos alcance $10,000 más '
                'IVA en cada línea de productos. Premio de $350 en Vale '
                'de Gasolina, una sola vez por línea.'
            ),
            'back_url': '/my/loyalty',
            'checklist': self._jaguen_get_checklist_data('pedido_linea'),
        })
        return request.render('jaguen_loyalty_portal.portal_my_loyalty_checklist', values)

    @http.route(['/my/loyalty/reward_image/<int:reward_id>'], type='http', auth='public')
    def jaguen_loyalty_reward_image(self, reward_id, **kw):
        reward = request.env['loyalty.reward'].sudo().browse(reward_id).exists()
        product = reward.reward_product_id if reward else request.env['product.product']
        record = product.sudo() if product else request.env['product.product'].sudo()
        stream = request.env['ir.binary']._get_image_stream_from(
            record, field_name='image_256',
        )
        return stream.get_response()
