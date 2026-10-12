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
        this._jaguenSyncTyc();
        return result;
    },

    /**
     * Sin la casilla de T&C marcada se bloquea el pago (el servidor tambien lo exige).
     * @override
     */
    start() {
        const result = this._super(...arguments);
        const box = document.getElementById('jaguen_tyc');
        if (box && !box.dataset.jaguenBound) {
            box.dataset.jaguenBound = '1';
            box.addEventListener('change', () => this._jaguenSyncTyc());
        }
        this._jaguenSyncTyc();
        return result;
    },

    /**
     * Odoo vuelve a habilitar el boton al elegir un metodo: se respeta la casilla de T&C.
     * @override
     */
    _enableButton() {
        const result = this._super(...arguments);
        this._jaguenSyncTyc();
        return result;
    },

    _jaguenSyncTyc() {
        const ok = !!document.getElementById('jaguen_tyc')?.checked;
        document.getElementById('jaguen_tyc_error')?.classList.toggle('d-none', ok);
        document.querySelectorAll('[name="o_payment_submit_button"]').forEach((el) => {
            if (el.tagName === 'BUTTON') {
                el.disabled = !ok;
            } else {
                el.style.pointerEvents = ok ? '' : 'none';
                el.style.opacity = ok ? '' : '0.4';
            }
        });
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
        params['jaguen_tyc'] = document.getElementById('jaguen_tyc')?.checked ? '1' : '';
        const select = document.getElementById('jaguen_card_type');
        if (select && this.paymentContext.providerCode === 'paypal') {
            params['jaguen_card_type'] = select.value;
        }
        return params;
    },

});
