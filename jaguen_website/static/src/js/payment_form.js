/** @odoo-module **/

import PaymentForm from '@payment/js/payment_form';

PaymentForm.include({

    /**
     * Muestra la pregunta credito/debito solo cuando la opcion de pago elegida es PayPal.
     * @override
     */
    async _expandInlineForm(radio) {
        const result = await this._super(...arguments);
        this._jaguenToggleCardType(this._getProviderCode(radio));
        return result;
    },

    _jaguenToggleCardType(providerCode) {
        document.getElementById('jaguen_card_type_box')
            ?.classList.toggle('d-none', providerCode !== 'paypal');
    },

    /**
     * Manda al servidor la respuesta (credit / debit) junto con la transaccion de PayPal.
     * @override
     */
    _prepareTransactionRouteParams() {
        const params = this._super(...arguments);
        const select = document.getElementById('jaguen_card_type');
        if (select && this.paymentContext.providerCode === 'paypal') {
            params['jaguen_card_type'] = select.value;
        }
        return params;
    },

});
