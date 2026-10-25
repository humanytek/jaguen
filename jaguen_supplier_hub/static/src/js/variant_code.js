/** @odoo-module **/

import VariantMixin from "@website_sale/js/sale_variant_mixin";

// Ficha del producto: al elegir una variante se muestra solo la clave de esa variante.
// Se envuelve la función del mixin antes de que website_sale.js la copie (el manifest lo carga 'before').
const baseOnChangeCombination = VariantMixin._onChangeCombination;
VariantMixin._onChangeCombination = function (ev, $parent, combination) {
    const result = baseOnChangeCombination.apply(this, arguments);
    if ($parent && $parent.is(".js_main_product")) {
        const el = document.querySelector(".apihub-variant-code");
        if (el && combination) {
            el.textContent = combination.apihub_clave || "";
        }
    }
    return result;
};
