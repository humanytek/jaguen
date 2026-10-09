# -*- coding: utf-8 -*-
"""
Candado de pago para los 4 programas de lealtad JAGUEN (JAGUEN Starter,
Rebate Anual, Mi Primer Pedido de $X, Mi Primer Pedido por Línea).

Decisión de negocio (confirmada con Javier, oct/2026): los puntos de
lealtad de un pedido NO deben contar como disponibles para el cliente
sino hasta que la factura correspondiente esté 100% pagada (estado
'paid' en account.move) - no basta con que el pedido se confirme, ni con
que la factura solo esté emitida. Un pedido facturado en varias facturas
parciales va liberando puntos conforme cada una de esas facturas se paga,
sin esperar a que el pedido completo esté liquidado.

CÓMO FUNCIONA (ver README del módulo para más detalle):

1. Odoo nativo (sale_loyalty) sigue sumando puntos a la loyalty.card tal
   cual al confirmar la orden (SaleOrder.action_confirm, ver
   odoo/addons/sale_loyalty/models/sale_order.py línea ~136-138:
   "for coupon, change in ...: coupon.points += change"). No tocamos ni
   reemplazamos ese mecanismo nativo - sería frágil y tendríamos que
   reimplementar toda la lógica de qué programas aplican, con código.

2. Inmediatamente después de que Odoo hace esa suma (extendemos
   action_confirm con un super() al inicio), RESTAMOS de vuelta esos
   mismos puntos de la card real y los guardamos "congelados" en un
   registro JaguenLoyaltyPendingPoints, uno por (card, pedido). La card
   queda con el mismo saldo visible que tenía antes de confirmar ese
   pedido - el cliente no ve ese progreso todavía en el portal.

3. Cuando una factura cambia su payment_state a 'paid' (vía
   base.automation en data/automation_data.xml, trigger declarativo,
   sin código aquí), se llama a
   account.move._jaguen_release_pending_loyalty_points(): por cada
   pedido de origen de esa factura, libera (suma de vuelta a la card
   real) la porción de puntos pendientes proporcional al monto de ESA
   factura sobre el total del pedido. Si el pedido se facturó en una
   sola factura (caso normal), se libera el 100% de una vez.

4. Si un pedido que ya pasó por el paso 2 (ya tiene puntos congelados) se
   CANCELA, SaleOrder._action_cancel nativo de sale_loyalty intenta
   restar de 'points' el mismo monto que ese pedido había dado - pero ese
   monto ya no está en 'points', está en 'x_puntos_pendientes'. Sin
   manejo especial, 'points' se va en negativo y los puntos congelados
   quedan huérfanos para siempre (bug real encontrado en pruebas,
   oct/2026 - ver jaguen-loyalty-portal-modulo.md). Por eso
   _action_cancel aquí deshace el congelamiento ANTES de dejar correr el
   nativo (ver _jaguen_unfreeze_cancelled_loyalty_points): devuelve a
   'points' lo que seguía pendiente de ese pedido, para que la resta
   nativa que viene justo después la neutralice y el saldo quede como si
   el pedido nunca se hubiera confirmado. La porción que ya se había
   liberado (si hubo pago parcial antes de cancelar) se respeta, no se
   quita.

Esto es best-effort: una vez instalado, aplica solo a pedidos confirmados
de aquí en adelante. Pedidos ya confirmados antes de instalar este
candado ya sumaron sus puntos de forma normal (no quedan retroactivamente
congelados) - ver nota en memoria del proyecto sobre esto.
"""
from odoo import fields, models


class LoyaltyCard(models.Model):
    _inherit = 'loyalty.card'

    x_puntos_pendientes = fields.Float(
        string='Puntos pendientes de pago (JAGUEN)',
        default=0.0,
        help=(
            "Puntos que un pedido ya le dio a esta tarjeta pero que "
            "todavía no se liberan al saldo visible del cliente, porque "
            "la factura correspondiente no está 100% pagada todavía. Se "
            "liberan automáticamente (se suman a 'points') conforme esa "
            "factura se va pagando - ver "
            "jaguen.loyalty.pending.points y "
            "account.move._jaguen_release_pending_loyalty_points()."
        ),
    )

    def _jaguen_is_accepted(self):
        """True si la empresa de esta tarjeta ya acepto los Terminos y
        Condiciones que abren este programa. Sin aceptar, no se gana nada
        (decision de negocio, oct/2026): Rebate Anual depende de 'acepta
        rebate anual'; JAGUEN Starter y los vales de Mi Primer Pedido
        dependen de 'acepta incentivos'. Las tarjetas de otros programas
        (sin grupo JAGUEN) no se tocan."""
        self.ensure_one()
        group = self.program_id.x_jaguen_loyalty_group
        if not group:
            return True
        partner = self.partner_id.commercial_partner_id.sudo()
        if not partner:
            return False
        if group == 'rebate':
            return bool(partner.x_acepta_rebate_anual)
        return bool(partner.x_acepta_incentivos_personales)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def action_confirm(self):
        # Odoo nativo hace su cálculo normal primero (sale_loyalty suma
        # coupon.points += change dentro de este mismo action_confirm,
        # vía super() más abajo en la cadena de herencia de Odoo). Lo
        # dejamos intacto - nunca lo reemplazamos.
        res = super().action_confirm()
        for order in self:
            order._jaguen_freeze_new_loyalty_points()
        return res

    def _action_cancel(self):
        # IMPORTANTE (bug encontrado en pruebas, oct/2026): sale_loyalty
        # nativo, al cancelar un pedido que ya estaba confirmado, hace
        # "coupon.points -= changes" (ver
        # odoo/addons/sale_loyalty/models/sale_order.py,
        # SaleOrder._action_cancel) usando el mismo monto que ese pedido
        # le había dado a la card al confirmarse. Pero si ese pedido ya
        # pasó por nuestro candado, esos puntos YA NO estaban en
        # card.points - los movimos a x_puntos_pendientes. Si dejamos que
        # Odoo nativo haga esa resta tal cual, card.points se va en
        # negativo (le resta algo que ya no tenía) y los puntos
        # congelados de ese pedido quedan huérfanos en x_puntos_pendientes
        # para siempre (nunca se liberan, porque el pedido ya está
        # cancelado y jamás se facturará/pagará).
        #
        # Por eso deshacemos ANTES el congelamiento de cada pedido que se
        # va a cancelar (devolvemos a points lo que todavía seguía
        # pendiente, y descontamos de x_puntos_pendientes), para que la
        # resta nativa que viene después quede neutralizada: Odoo resta
        # el monto original, nosotros ya lo habíamos devuelto, el saldo
        # neto queda igual que antes de confirmar ese pedido.
        for order in self.filtered(lambda s: s.state == 'sale'):
            order._jaguen_unfreeze_cancelled_loyalty_points()
        return super()._action_cancel()

    def _jaguen_unfreeze_cancelled_loyalty_points(self):
        """Inverso de _jaguen_freeze_new_loyalty_points: por cada registro
        jaguen.loyalty.pending.points de ESTE pedido que todavía tenga
        puntos sin liberar (points_total > points_released), devuelve esa
        porción no liberada a card.points (de donde Odoo nativo la va a
        restar un instante después, al cancelar) y la quita de
        x_puntos_pendientes. La porción YA liberada (points_released, si
        hubo un pago parcial antes de cancelar) se deja intacta - ya es
        saldo real del cliente, ganado de buena fe, y no se le quita por
        cancelar el resto del pedido.

        Importante (oct/2026): NO se borra (unlink) el registro pending
        al final, aunque ya no quede nada por liberar - se deja con
        points_total = points_released (0 puntos realmente pendientes),
        por dos motivos: (1) si el pedido se reactiva después (reset a
        borrador + reconfirmar), _jaguen_freeze_new_loyalty_points lo
        encuentra y lo REUTILIZA en vez de crear uno nuevo, evitando que
        puedan coexistir dos registros del mismo pedido+tarjeta (eso es
        lo que permitía una liberación duplicada de puntos); (2) una
        nota de crédito posterior contra una factura de este pedido ya
        cancelado sigue pudiendo encontrar la tarjeta afectada a través
        de este registro, aunque coupon_point_ids ya esté vacío (ver
        _jaguen_get_loyalty_cards_of_order) - antes de este cambio, esa
        NC se publicaba sin restar ningún punto, sin aviso ni error."""
        self.ensure_one()
        Pending = self.env['jaguen.loyalty.pending.points'].sudo()
        pendings = Pending.search([('order_id', '=', self.id)])
        for pe in pendings:
            card = pe.card_id
            # Lo que Odoo nativo va a restar de card.points un instante
            # despues, al cancelar: todo lo que este pedido le dio a esta
            # tarjeta (coupon_point_ids), lo pendiente Y lo ya liberado.
            # Lo devolvemos completo para neutralizar esa resta: asi la
            # porcion ya liberada (pagada) del cliente se respeta tambien
            # cuando el pedido estaba 100% pagado (bug oct/2026: la
            # tarjeta caia a 0 al cancelar un pedido pagado).
            native = sum(self.coupon_point_ids.sudo().filtered(
                lambda l: l.coupon_id == card).mapped('points'))
            remaining = pe.points_total - pe.points_released
            if native > 0 or remaining > 0:
                card.sudo().write({
                    'points': card.points + native,
                    'x_puntos_pendientes': max(0.0, card.x_puntos_pendientes - max(remaining, 0.0)),
                })
            if remaining > 0:
                pe.points_total = pe.points_released

    def _jaguen_freeze_new_loyalty_points(self):
        """Resta de 'points' (saldo visible) y mueve a 'x_puntos_pendientes'
        los puntos que ESTE pedido le acaba de dar a cada una de sus
        tarjetas de lealtad, justo después de confirmarse. Se identifica
        cuánto le dio este pedido en particular vía
        sale.order.coupon_point_ids (el registro nativo de Odoo que
        rastrea cuánto aportó cada pedido a cada tarjeta).

        Defensa extra (oct/2026): si por cualquier motivo ya existe un
        registro jaguen.loyalty.pending.points de este mismo (pedido,
        tarjeta) - por ejemplo un huérfano que sobrevivió una cancelación
        de antes de este fix, o un reintento del propio action_confirm -
        lo reutilizamos en vez de crear uno nuevo, para que nunca puedan
        coexistir dos registros pendientes del mismo pedido+tarjeta (eso
        es lo que permitía la liberación duplicada de puntos, ver
        _jaguen_release_pending_loyalty_points)."""
        self.ensure_one()
        Pending = self.env['jaguen.loyalty.pending.points'].sudo()
        for pe in self.coupon_point_ids.sudo():
            points = pe.points
            if not points or points <= 0:
                continue
            card = pe.coupon_id
            # Tarjetas inactivas (p. ej. Rebate Anual de un cliente que
            # sigue en onboarding, o un segundo vale de "solo 1 vez por
            # cliente"): no cuentan para el cliente, asi que no se congela
            # nada en ellas.
            if not card.active:
                continue
            # No todos los programas de JAGUEN deben pasar por este
            # candado - solo los 4 ligados a compra/pago de un pedido.
            # Dejamos cualquier otro programa (si lo hubiera) sin tocar.
            if not card.program_id.x_jaguen_loyalty_group:
                continue
            if not card._jaguen_is_accepted():
                # Sin aceptar los Terminos y Condiciones no se gana nada: se
                # quitan estos puntos de la tarjeta y se deja un registro en
                # 0 (marca de que este pedido no dio puntos, para que la
                # cancelacion y las notas de credito no resten de mas).
                card.sudo().write({'points': card.points - points})
                if not Pending.search([('order_id', '=', self.id), ('card_id', '=', card.id)], limit=1):
                    Pending.create({
                        'order_id': self.id, 'card_id': card.id,
                        'points_total': 0.0, 'points_released': 0.0,
                    })
                continue
            card.sudo().write({
                'points': card.points - points,
                'x_puntos_pendientes': card.x_puntos_pendientes + points,
            })
            existing = Pending.search([
                ('order_id', '=', self.id),
                ('card_id', '=', card.id),
            ], limit=1)
            if existing:
                existing.points_total += points
            else:
                Pending.create({
                    'order_id': self.id,
                    'card_id': card.id,
                    'points_total': points,
                    'points_released': 0.0,
                })


class JaguenLoyaltyPendingPoints(models.Model):
    _name = 'jaguen.loyalty.pending.points'
    _description = 'Puntos de lealtad congelados por pedido, a la espera de pago de factura'

    order_id = fields.Many2one('sale.order', required=True, ondelete='cascade', index=True)
    card_id = fields.Many2one('loyalty.card', required=True, ondelete='cascade', index=True)
    points_total = fields.Float(required=True, help='Puntos que este pedido le dio a esta tarjeta en total.')
    points_released = fields.Float(default=0.0, help='Cuánto de points_total ya se liberó al saldo visible (points) de la tarjeta.')


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _jaguen_get_source_orders(self):
        """Pedido(s) de venta de origen de esta factura o nota de crédito.
        Para una nota de crédito generada con el wizard estándar de Odoo
        ("Agregar nota de crédito" desde una factura), usa
        reversed_entry_id primero - es más confiable que sale_line_ids,
        que puede venir vacío si la nota de crédito no copió las líneas
        originales. Si no hay reversed_entry_id (nota de crédito hecha a
        mano, sin partir de una factura), cae al mismo patrón que ya
        usamos para facturas normales."""
        self.ensure_one()
        if self.reversed_entry_id:
            return self.reversed_entry_id.line_ids.sale_line_ids.order_id
        return self.line_ids.sale_line_ids.order_id

    def _jaguen_points_per_peso(self, program):
        """Tasa de conversión de $ a puntos de un programa (ej. 0.862069
        para JAGUEN Starter y Rebate Anual) - se lee de su primera regla
        con reward_point_mode 'money', igual que la que Odoo ya usa para
        calcular puntos al confirmar un pedido. 0 si el programa no tiene
        una regla de ese tipo (no debería pasar en los 4 programas de
        JAGUEN, pero se cubre por seguridad)."""
        rule = program.rule_ids.filtered(lambda r: r.reward_point_mode == 'money')[:1]
        return rule.reward_point_amount if rule else 0.0

    def _jaguen_get_loyalty_cards_of_order(self, order):
        """Tarjetas de lealtad (de los 4 programas JAGUEN) afectadas por
        un pedido, para usarse al restar puntos por nota de crédito.

        Normalmente basta con order.coupon_point_ids.coupon_id (el
        registro nativo de Odoo). Pero cancelar un pedido vacía por
        completo coupon_point_ids (comportamiento nativo de
        sale_loyalty, no de este módulo) - así que si el pedido ya está
        cancelado (o por cualquier otro motivo coupon_point_ids viene
        vacío), caemos a los card_id de jaguen.loyalty.pending.points de
        ese pedido, que es la única referencia que sobrevive a una
        cancelación (bug encontrado en pruebas, oct/2026 - una NC contra
        la factura de un pedido ya cancelado no restaba ningún punto,
        sin aviso ni error)."""
        cards = order.coupon_point_ids.coupon_id.sudo()
        if not cards:
            Pending = self.env['jaguen.loyalty.pending.points'].sudo()
            # Solo registros con puntos reales: un registro en 0 (p. ej. de
            # una tarjeta vieja que quedo atras al reactivar el pedido) no
            # debe recibir la resta de la nota de credito.
            cards = Pending.search([
                ('order_id', '=', order.id),
                ('points_total', '>', 0),
            ]).card_id
        return cards

    def _jaguen_apply_credit_note_to_loyalty(self):
        """Resta de la tarjeta de lealtad del cliente los puntos
        equivalentes al monto de una nota de crédito, para los 4
        programas JAGUEN. Se llama vía base.automation cuando una nota
        de crédito (move_type='out_refund') se publica (state='posted').

        Siempre resta, sin importar qué tan vieja sea la venta original
        (decisión de negocio, oct/2026 - importa sobre todo para Rebate
        Anual, cuya meta se evalúa una vez al año contra el acumulado:
        una nota de crédito de meses atrás debe bajar ese acumulado antes
        del cierre de enero). Resta primero de puntos pendientes (caso
        normal: la NC se hace antes de que la factura se pague, así que
        esos puntos ni siquiera se habían liberado todavía); si no
        alcanza ahí, resta del saldo real (caso de una NC después de
        pagado y liberado) y puede dejarlo en negativo - se recupera con
        compras futuras."""
        Pending = self.env['jaguen.loyalty.pending.points'].sudo()
        for move in self.filtered(lambda m: m.move_type == 'out_refund' and m.state == 'posted'):
            orders = move._jaguen_get_source_orders()
            if not orders:
                continue
            for order in orders:
                # Cuánto de esta nota de crédito corresponde a este
                # pedido en particular (normalmente solo hay un pedido,
                # pero una NC puede en teoría tocar líneas de varios).
                order_lines = move.line_ids.filtered(lambda l: l.sale_line_ids.order_id == order)
                nc_amount = sum(order_lines.mapped('price_total')) if order_lines else move.amount_total
                if not nc_amount:
                    continue
                for card in move._jaguen_get_loyalty_cards_of_order(order):
                    if not card.program_id.x_jaguen_loyalty_group:
                        continue
                    points_per_peso = move._jaguen_points_per_peso(card.program_id)
                    if not points_per_peso:
                        continue
                    points_to_remove = nc_amount * points_per_peso
                    pending = Pending.search([('order_id', '=', order.id), ('card_id', '=', card.id)], limit=1)
                    if pending and not pending.points_total and not pending.points_released:
                        # Este pedido nunca dio puntos a esta tarjeta (no
                        # acepto los Terminos, o ya se agotaron): no hay
                        # nada que restar.
                        continue
                    if pending and pending.points_total > pending.points_released:
                        from_pending = min(points_to_remove, pending.points_total - pending.points_released)
                        pending.points_total -= from_pending
                        card.sudo().x_puntos_pendientes = max(0.0, card.x_puntos_pendientes - from_pending)
                        points_to_remove -= from_pending
                    if points_to_remove > 0:
                        card.sudo().points = card.points - points_to_remove

    def _jaguen_release_pending_loyalty_points(self):
        """Libera puntos pendientes al saldo visible del cliente para los
        pedidos de origen de esta factura, en proporción al monto de ESTA
        factura sobre el total de cada pedido. Se llama vía
        base.automation (automation_data.xml) cuando payment_state pasa
        a 'paid'."""
        Pending = self.env['jaguen.loyalty.pending.points'].sudo()
        for move in self.filtered(lambda m: m.move_type == 'out_invoice' and m.payment_state == 'paid'):
            orders = move.line_ids.sale_line_ids.order_id
            if not orders:
                continue
            for order in orders:
                pendings = Pending.search([('order_id', '=', order.id)])
                if not pendings:
                    continue
                # Proporción ACUMULADA de este pedido ya pagada al día de
                # hoy (todas sus facturas pagadas, incluida esta, sobre el
                # total facturado del pedido) - no solo esta factura. Así
                # un pedido con varias facturas libera correctamente la
                # diferencia contra lo que facturas anteriores ya
                # liberaron, sin depender del orden en que se paguen.
                # Caso normal (1 pedido = 1 factura): ratio = 1.0, se
                # libera todo de un jalón al pagarse.
                order_invoices = order.invoice_ids.filtered(lambda m: m.move_type == 'out_invoice' and m.state == 'posted')
                # El denominador es el total del PEDIDO (sobre el que se
                # calcularon los puntos al confirmar), no solo lo facturado
                # hasta hoy: si un pedido se factura en partes (entregas
                # parciales), pagar la primera factura no debe liberar el
                # 100% de los puntos solo porque aun no existe la segunda
                # (bug oct/2026). Si por ajustes se facturo mas que el
                # total del pedido, se usa lo facturado.
                order_invoiced_total = max(
                    order.amount_total,
                    sum(order_invoices.mapped('amount_total')),
                )
                order_paid_total = sum(order_invoices.filtered(lambda m: m.payment_state == 'paid').mapped('amount_total'))
                ratio = (order_paid_total / order_invoiced_total) if order_invoiced_total else 1.0
                ratio = min(1.0, max(0.0, ratio))
                for pe in pendings:
                    if pe.card_id.program_id.x_jaguen_loyalty_group in ('pedido_monto', 'pedido_linea'):
                        # Vales de "logro unico" (1 punto): todo o nada, sin
                        # fracciones de punto cuando el pedido se factura en
                        # varias facturas. Se liberan al pagarse TODO el pedido.
                        if ratio < 0.999999:
                            continue
                        to_release = pe.points_total - pe.points_released
                    else:
                        to_release = round(pe.points_total * ratio - pe.points_released, 6)
                    if to_release <= 0:
                        continue
                    remaining = pe.points_total - pe.points_released
                    to_release = min(to_release, remaining)
                    if to_release <= 0:
                        continue
                    card = pe.card_id
                    vals = {'x_puntos_pendientes': max(0.0, card.x_puntos_pendientes - to_release)}
                    if card._jaguen_is_accepted():
                        vals['points'] = card.points + to_release
                    # Si no acepto los Terminos al momento de pagar, esos
                    # puntos no se acreditan (se dan por liberados en vacio).
                    card.sudo().write(vals)
                    pe.points_released += to_release
