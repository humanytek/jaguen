# -*- coding: utf-8 -*-
"""Regresión de los 3 bugs del candado de pago (models/loyalty_payment_gate.py).

Bug #1 (be9432b): cancelar un pedido confirmado dejaba card.points en negativo
                  y/o quitaba puntos ya liberados por una factura pagada.
Bug #2 (4960461): cancelar y reconfirmar un pedido duplicaba los puntos al
                  pagarse la factura (dos registros pending del mismo pedido+tarjeta).
Bug #3 (4960461): una nota de crédito contra la factura de un pedido cancelado
                  no restaba puntos (coupon_point_ids vacío tras cancelar).
"""
from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'jaguen_loyalty')
class TestPaymentGate(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.program = cls.env.ref('jaguen_loyalty_portal.program_onboarding')
        cls.rate = cls.program.rule_ids[:1].reward_point_amount  # 0.862069
        cls.partner = cls.env['res.partner'].create({
            'name': 'Cliente Prueba Lealtad',
            'x_acepta_incentivos_personales': True,
        })
        cls.card = cls.env['loyalty.card'].create({
            'program_id': cls.program.id,
            'partner_id': cls.partner.id,
            'points': 0,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Producto lealtad (test)',
            'type': 'service',
            'list_price': 1000.0,
            'invoice_policy': 'order',
            'taxes_id': [Command.clear()],
        })

    # -- helpers ---------------------------------------------------------
    def _order(self, qty=1):
        return self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [Command.create({
                'product_id': self.product.id,
                'product_uom_qty': qty,
                'price_unit': 1000.0,
                'tax_id': [Command.clear()],
            })],
        })

    def _pending(self, order):
        return self.env['jaguen.loyalty.pending.points'].sudo().search([
            ('order_id', '=', order.id), ('card_id', '=', self.card.id)])

    def _confirm(self, order):
        order.action_confirm()
        self.card.invalidate_recordset()

    def _invoice_and_pay(self, order):
        invoice = order._create_invoices()
        invoice.action_post()
        invoice.write({'payment_state': 'paid'})
        invoice._jaguen_release_pending_loyalty_points()  # idempotente
        self.card.invalidate_recordset()
        return invoice

    def _credit_note(self, invoice, amount=None):
        wiz = self.env['account.move.reversal'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({
                'journal_id': invoice.journal_id.id,
                'reason': 'test',
            })
        refund = self.env['account.move'].browse(wiz.refund_moves()['res_id'])
        refund.action_post()
        refund._jaguen_apply_credit_note_to_loyalty()
        self.card.invalidate_recordset()
        return refund

    # -- sanity ------------------------------------------------------------
    def test_00_confirm_freezes_points(self):
        order = self._order()
        self._confirm(order)
        pending = self._pending(order)
        self.assertEqual(len(pending), 1)
        self.assertAlmostEqual(pending.points_total, 1000 * self.rate, places=2)
        self.assertAlmostEqual(self.card.points, 0.0, places=2)
        self.assertAlmostEqual(self.card.x_puntos_pendientes, pending.points_total, places=2)

    def test_01_paid_invoice_releases_all(self):
        order = self._order()
        self._confirm(order)
        self._invoice_and_pay(order)
        self.assertAlmostEqual(self.card.points, 1000 * self.rate, places=2)
        self.assertAlmostEqual(self.card.x_puntos_pendientes, 0.0, places=2)

    # -- Liberacion proporcional con facturas parciales ---------------------
    def test_05_partial_invoice_releases_proportionally(self):
        """Pedido de $10,000 facturado en dos partes: al pagar solo la primera
        (20%) debe liberarse el 20%, no el 100%."""
        order = self._order(qty=10)
        self._confirm(order)
        inv1 = order._create_invoices(final=False)
        inv1.invoice_line_ids.write({'quantity': 2})
        inv1.action_post()
        inv1.write({'payment_state': 'paid'})
        inv1._jaguen_release_pending_loyalty_points()
        self.card.invalidate_recordset()
        self.assertAlmostEqual(self.card.points, 10000 * self.rate * 0.2, places=2)

    def test_06_inactive_card_is_not_frozen(self):
        self.card.active = False
        order = self._order()
        self._confirm(order)
        self.assertFalse(self._pending(order))

    # -- Sin aceptar los Terminos no se gana nada -------------------------
    def test_40_not_accepted_earns_nothing(self):
        self.partner.x_acepta_incentivos_personales = False
        order = self._order()
        self._confirm(order)
        self.assertAlmostEqual(self.card.points, 0.0, places=2)
        self.assertAlmostEqual(self.card.x_puntos_pendientes, 0.0, places=2)
        invoice = self._invoice_and_pay(order)
        self.assertAlmostEqual(self.card.points, 0.0, places=2)
        # cancelar y nota de credito no dejan saldo negativo
        order._action_cancel()
        self.card.invalidate_recordset()
        self.assertAlmostEqual(self.card.points, 0.0, places=2)
        self._credit_note(invoice)
        self.assertAlmostEqual(self.card.points, 0.0, places=2)

    def test_41_accepting_later_earns_only_new_purchases(self):
        self.partner.x_acepta_incentivos_personales = False
        before = self._order()
        self._confirm(before)
        self._invoice_and_pay(before)
        self.partner.x_acepta_incentivos_personales = True
        after = self._order()
        self._confirm(after)
        self._invoice_and_pay(after)
        self.assertAlmostEqual(self.card.points, 1000 * self.rate, places=2)

    def test_42_voided_points_do_not_get_subtracted_by_credit_note(self):
        """Acepta al confirmar, desacepta antes de pagar (puntos anulados),
        luego una nota de credito: no debe restar puntos que nunca se acreditaron."""
        order = self._order()
        self._confirm(order)
        self.partner.x_acepta_incentivos_personales = False
        invoice = self._invoice_and_pay(order)
        self.assertAlmostEqual(self.card.points, 0.0, places=2)
        self.partner.x_acepta_incentivos_personales = True
        self._credit_note(invoice)
        self.assertAlmostEqual(self.card.points, 0.0, places=2)

    # -- Bug #1 ------------------------------------------------------------
    def test_10_cancel_confirmed_order_no_negative(self):
        order = self._order()
        self._confirm(order)
        order._action_cancel()
        self.card.invalidate_recordset()
        self.assertGreaterEqual(self.card.points, 0.0, 'Saldo negativo tras cancelar')
        self.assertAlmostEqual(self.card.points, 0.0, places=2)
        self.assertAlmostEqual(self.card.x_puntos_pendientes, 0.0, places=2)

    def test_11_cancel_keeps_already_released_points(self):
        """Pedido en 2 facturas: una pagada (puntos liberados) y otra no.
        Cancelar el pedido no debe quitar lo ya liberado."""
        order = self._order(qty=10)  # $10,000
        self._confirm(order)
        total = 10000 * self.rate
        inv1 = order.with_context(raise_if_nothing_to_invoice=True)._create_invoices(final=False)
        # factura parcial: reduce a 2 de las 10 unidades
        inv1.invoice_line_ids.write({'quantity': 2})
        inv1.action_post()
        inv1.write({'payment_state': 'paid'})
        inv1._jaguen_release_pending_loyalty_points()
        self.card.invalidate_recordset()
        released = self.card.points
        self.assertAlmostEqual(released, total * 0.2, places=2)
        order._action_cancel()
        self.card.invalidate_recordset()
        self.assertAlmostEqual(self.card.points, released, places=2,
                               msg='Cancelar quitó puntos ya liberados')
        self.assertAlmostEqual(self.card.x_puntos_pendientes, 0.0, places=2)

    def test_12_cancel_fully_paid_order_keeps_points(self):
        order = self._order()
        self._confirm(order)
        self._invoice_and_pay(order)
        released = self.card.points
        order._action_cancel()
        self.card.invalidate_recordset()
        self.assertAlmostEqual(self.card.points, released, places=2)

    # -- Bug #2 ------------------------------------------------------------
    def test_20_cancel_reactivate_does_not_duplicate(self):
        order = self._order()
        self._confirm(order)
        order._action_cancel()
        order.action_draft()
        self._confirm(order)
        self.assertEqual(len(self._pending(order)), 1,
                         'Coexisten dos registros pending del mismo pedido+tarjeta')
        self._invoice_and_pay(order)
        self.assertAlmostEqual(self.card.points, 1000 * self.rate, places=2,
                               msg='Puntos duplicados tras cancelar/reactivar')
        self.assertAlmostEqual(self.card.x_puntos_pendientes, 0.0, places=2)

    def test_21_cancel_does_not_unlink_pending(self):
        order = self._order()
        self._confirm(order)
        order._action_cancel()
        pending = self._pending(order)
        self.assertEqual(len(pending), 1)
        self.assertAlmostEqual(pending.points_total, pending.points_released, places=6)

    # -- Bug #3 ------------------------------------------------------------
    def test_30_credit_note_on_active_order_control(self):
        order = self._order()
        self._confirm(order)
        invoice = self._invoice_and_pay(order)
        self._credit_note(invoice)
        self.assertAlmostEqual(self.card.points, 0.0, places=2)

    def test_31_credit_note_on_cancelled_order_subtracts(self):
        """Factura pagada (puntos liberados), luego se cancela el pedido y se
        hace NC total: debe restar aunque coupon_point_ids esté vacío."""
        order = self._order()
        self._confirm(order)
        invoice = self._invoice_and_pay(order)
        before = self.card.points
        self.assertAlmostEqual(before, 1000 * self.rate, places=2)
        order._action_cancel()
        self.assertFalse(order.coupon_point_ids, 'Se esperaba coupon_point_ids vacío')
        self.card.invalidate_recordset()
        after_cancel = self.card.points
        self.assertAlmostEqual(after_cancel, before, places=2,
                               msg='Cancelar un pedido pagado quito puntos liberados')
        self._credit_note(invoice)
        self.assertLess(self.card.points, after_cancel,
                        'La NC contra pedido cancelado no restó puntos')

    def test_32_helper_falls_back_to_pending(self):
        order = self._order()
        self._confirm(order)
        order._action_cancel()
        self.assertFalse(order.coupon_point_ids)
        move = self.env['account.move']
        self.assertEqual(move._jaguen_get_loyalty_cards_of_order(order), self.card)


@tagged('post_install', '-at_install', 'jaguen_loyalty')
class TestJaguenOrderRules(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.partner'].create({'name': 'EMPRESA PRUEBA SA', 'is_company': True})
        cls.person = cls.env['res.partner'].create({
            'name': 'Juan Prueba', 'parent_id': cls.company.id, 'type': 'contact'})
        cls.product = cls.env['product.product'].create({
            'name': 'Producto reglas (test)', 'type': 'service', 'list_price': 1000.0,
            'taxes_id': [Command.clear()]})

    def _order(self, partner):
        return self.env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [Command.create({'product_id': self.product.id, 'product_uom_qty': 1})],
        })

    def test_invoice_address_is_company_but_customer_and_delivery_untouched(self):
        order = self._order(self.person)
        self.assertEqual(order.partner_id, self.person)
        self.assertEqual(order.partner_invoice_id, self.company)
        self.assertEqual(order.partner_shipping_id, self.person)

    def test_invoice_address_write_is_normalized(self):
        order = self._order(self.person)
        order.write({'partner_invoice_id': self.person.id})
        self.assertEqual(order.partner_invoice_id, self.company)

    def test_own_order_points_not_claimable(self):
        program = self.env.ref('jaguen_loyalty_portal.program_onboarding')
        card = self.env['loyalty.card'].create({
            'program_id': program.id, 'partner_id': self.person.id, 'points': 0})
        order = self._order(self.person)
        self.env['sale.order.coupon.points'].create({
            'order_id': order.id, 'coupon_id': card.id, 'points': 50000})
        self.assertEqual(order._get_real_points_for_coupon(card), 0.0)


@tagged('post_install', '-at_install', 'jaguen_loyalty')
class TestMontoHighestTier(TransactionCase):
    """Mi Primer Pedido de $X: un pedido otorga solo el vale mas alto disponible."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.partner'].create({
            'name': 'EMPRESA TIERS SA', 'is_company': True,
            'x_acepta_incentivos_personales': True})
        cls.person = cls.env['res.partner'].create({
            'name': 'Persona Tiers', 'parent_id': cls.company.id, 'type': 'contact'})
        cls.product = cls.env['product.product'].create({
            'name': 'Producto tiers (test)', 'type': 'service', 'list_price': 1000.0,
            'taxes_id': [Command.clear()]})

    def _confirm_order(self, amount):
        order = self.env['sale.order'].create({
            'partner_id': self.person.id,
            'order_line': [Command.create({
                'product_id': self.product.id, 'product_uom_qty': 1, 'price_unit': amount})],
        })
        order.action_confirm()
        return order

    def _earned(self):
        cards = self.env['loyalty.card'].with_context(active_test=False).search([
            ('partner_id', 'child_of', self.company.id),
            ('program_id.x_jaguen_loyalty_group', '=', 'pedido_monto'),
            ('active', '=', True)])
        return sorted(c.program_id.rule_ids[:1].minimum_amount for c in cards)

    def test_first_order_only_highest(self):
        self._confirm_order(60000)
        self.assertEqual(self._earned(), [50000])

    def test_second_order_next_highest(self):
        self._confirm_order(60000)
        self._confirm_order(60000)
        self.assertEqual(self._earned(), [45000, 50000])

    def test_mid_amount(self):
        self._confirm_order(22500)
        self.assertEqual(self._earned(), [20000])
        self._confirm_order(22500)
        self.assertEqual(self._earned(), [15000, 20000])


@tagged('post_install', '-at_install', 'jaguen_loyalty')
class TestGiftChoiceRewards(TransactionCase):
    """Starter y Mi Primer Pedido de $X: cada tramo se canjea escogiendo 1 de 2 productos."""

    def test_rewards_are_two_product_choice(self):
        Reward = self.env['loyalty.reward']
        rewards = Reward.search([('program_id.x_jaguen_loyalty_group', 'in', ['onboarding', 'pedido_monto'])])
        self.assertEqual(len(rewards), 20)
        for reward in rewards:
            self.assertEqual(reward.reward_type, 'product', reward.program_id.name)
            self.assertTrue(reward.multi_product, reward.program_id.name)
            self.assertEqual(len(reward.reward_product_ids), 2, reward.program_id.name)

    def test_gift_products_are_not_sellable(self):
        gifts = self.env['product.product'].search([('name', 'like', 'Regalo %')])
        self.assertGreaterEqual(len(gifts), 40)
        self.assertFalse(gifts.filtered('sale_ok'))

    def test_claim_gives_exactly_one_gift(self):
        """Con 30,000 puntos, canjear el premio de 10,000 da 1 regalo y cuesta 10,000."""
        program = self.env.ref('jaguen_loyalty_portal.program_onboarding')
        reward = self.env.ref('jaguen_loyalty_portal.reward_onboarding_10000')
        partner = self.env['res.partner'].create({'name': 'Cliente canje', 'x_acepta_incentivos_personales': True})
        card = self.env['loyalty.card'].create({'program_id': program.id, 'partner_id': partner.id, 'points': 30000})
        order = self.env['sale.order'].create({
            'partner_id': partner.id,
            'order_line': [Command.create({
                'product_id': self.env['product.product'].create({'name': 'P canje', 'type': 'service', 'list_price': 100}).id,
                'product_uom_qty': 1})]})
        vals = order._get_reward_values_product(reward, card)
        self.assertEqual(vals[0]['product_uom_qty'], 1)
        self.assertEqual(vals[0]['points_cost'], 10000)
