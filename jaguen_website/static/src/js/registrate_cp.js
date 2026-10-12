/* Registrate: al escribir el codigo postal se llenan estado, ciudad y localidad (catalogo SEPOMEX) y la colonia pasa a ser
   una lista con 2 opciones extra ("Otra no especificada" y "Escribir mi colonia"). Todo se puede corregir a mano. */
(function () {
    'use strict';
    var OTRA = 'Otra no especificada en el catálogo';

    function q(name) { return document.querySelector('[name="' + name + '"]'); }

    function setSelect(el, id) {
        if (!el || !id) { return; }
        var opt = el.querySelector('option[value="' + id + '"]');
        if (opt) { el.value = String(id); el.dispatchEvent(new Event('change', {bubbles: true})); }
    }

    function setText(el, value) {
        if (!el || !value) { return; }
        el.value = value;
        el.dispatchEvent(new Event('input', {bubbles: true}));
    }

    function coloniaWidget(input) {
        var sel = input.parentNode.querySelector('.jg-colonia-sel');
        if (sel) { return sel; }
        sel = document.createElement('select');
        sel.className = 'form-select jg-colonia-sel';
        input.parentNode.insertBefore(sel, input);
        sel.addEventListener('change', function () {
            if (sel.value === '__otra__') {
                input.value = OTRA;
                input.style.display = 'none';
            } else if (sel.value === '__escribir__') {
                input.value = '';
                input.style.display = '';
                input.focus();
            } else {
                input.value = sel.value;
                input.style.display = 'none';
            }
            input.dispatchEvent(new Event('input', {bubbles: true}));
        });
        return sel;
    }

    function fillColonias(input, colonias) {
        var sel = coloniaWidget(input);
        if (input.dataset.jgReq === undefined) { input.dataset.jgReq = input.required ? '1' : '0'; }
        var html = '<option value="">Selecciona tu colonia</option>';
        colonias.forEach(function (c) {
            var n = c.n.replace(/"/g, '&quot;');
            html += '<option value="' + n + '">' + c.n + (c.t && c.t !== 'Colonia' ? ' (' + c.t + ')' : '') + '</option>';
        });
        html += '<option value="__otra__">' + OTRA + '</option><option value="__escribir__">Escribir mi colonia</option>';
        sel.innerHTML = html;
        sel.required = input.dataset.jgReq === '1';
        sel.style.display = '';
        input.value = '';
        input.style.display = 'none';
        input.required = false;
    }

    function noCatalog(input) {
        var sel = input.parentNode.querySelector('.jg-colonia-sel');
        if (sel) { sel.remove(); }
        input.style.display = '';
        if (input.dataset.jgReq === '1') { input.required = true; }
    }

    function lookup(cp, cb) {
        fetch('/jaguen/cp/' + cp, {headers: {'Accept': 'application/json'}})
            .then(function (r) { return r.json(); }).then(cb).catch(function () { cb({}); });
    }

    function bind(cfg) {
        var zip = q(cfg.zip), col = q(cfg.colonia);
        if (!zip || !col || zip.dataset.jgBound) { return; }
        zip.dataset.jgBound = '1';
        var last = '';
        function run() {
            var cp = (zip.value || '').replace(/\D/g, '');
            if (cp.length !== 5 || cp === last) { return; }
            last = cp;
            lookup(cp, function (d) {
                if (!d || !d.colonias) { noCatalog(col); return; }
                fillColonias(col, d.colonias);
                cfg.apply(d);
            });
        }
        zip.addEventListener('input', run);
        zip.addEventListener('change', run);
        zip.addEventListener('blur', run);
    }

    function init() {
        // Domicilio fiscal: estado, ciudad y localidad son catalogos del SAT (listas); se eligen solos pero se pueden cambiar.
        bind({zip: 'zip', colonia: 'l10n_mx_edi_colony', apply: function (d) {
            setSelect(q('state_id'), d.estado_id);
            setTimeout(function () {
                setSelect(q('city_id'), d.ciudad_id);
                setSelect(q('l10n_mx_edi_locality_id'), d.localidad_id);
            }, 400);
        }});
        // Direccion de entrega: ciudad y estado son texto libre.
        bind({zip: 'jaguen_ship_zip', colonia: 'jaguen_ship_colony', apply: function (d) {
            setText(q('jaguen_ship_city'), d.ciudad);
            setText(q('jaguen_ship_state'), d.estado);
        }});
    }

    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
    // el formulario de Odoo puede pintarse un poco despues
    setTimeout(init, 1500);
})();
