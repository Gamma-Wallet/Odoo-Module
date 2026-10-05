/** @odoo-module **/

import paymentPostProcessing from '@payment/js/post_processing';

paymentPostProcessing.include({
    /**
     * A store-credit payment stays pending until the customer settles it in Gamma Wallet, which
     * happens on the order confirmation page (it shows the QR code). Go there at once.
     *
     * @override method from `@payment/js/post_processing`
     */
    _getFinalStates(providerCode) {
        const finalStates = this._super(...arguments);
        if (providerCode === 'gamma_wallet') {
            finalStates.add('pending');
        }
        return finalStates;
    },
});
