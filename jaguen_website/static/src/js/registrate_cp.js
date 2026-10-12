/* Registrate: al escribir el codigo postal se llenan estado, ciudad y localidad (catalogo SEPOMEX) y la colonia pasa a ser
   una lista con 2 opciones extra ("Otra no especificada" y "Escribir mi colonia"). Todo se puede corregir a mano. */
(function () {
    'use strict';
    var OTRA = 'Otra no especificada en el catálogo';

    function q(name) { return document.querySelector('[name="' + name + '"]'); }

    function setSelect(el, id) {
        if (!el) { return; }
        if (!id) {  // no hay equivalente para este CP: se limpia lo que quedo del CP anterior
            if (el.value) { el.value = ''; el.dispatchEvent(new Event('change', {bubbles: true})); }
            return;
        }
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

    var pendingColonia = '';

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
        if (pendingColonia && input.name === 'l10n_mx_edi_colony') {
            // colonia que traia la CSF: se elige la que coincida del catalogo; si no, se escribe tal cual
            var nsp = function (t) { return normTxt(t).replace(/ /g, ''); };
            var want = nsp(pendingColonia), hit = null;
            Array.prototype.forEach.call(sel.options, function (o) { if (!hit && o.value && o.value[0] !== '_' && nsp(o.value) === want) { hit = o; } });
            if (hit) { sel.value = hit.value; input.value = hit.value; } else {
                sel.value = '__escribir__'; input.value = pendingColonia; input.style.display = '';
            }
            pendingColonia = '';
        }
    }

    function normTxt(t) { return String(t || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase().replace(/[^A-Z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim(); }

    // Si el cliente toca un campo autollenado, ya es suyo: otra constancia no lo vuelve a pisar.
    document.addEventListener('input', function (ev) {
        if (ev.isTrusted && ev.target && ev.target.dataset) { delete ev.target.dataset.jgAuto; }
    }, true);
    document.addEventListener('change', function (ev) {
        if (ev.isTrusted && ev.target && ev.target.dataset) { delete ev.target.dataset.jgAuto; }
    }, true);

    // Autollenado con los datos de la CSF: solo se llenan campos vacios o llenados antes por el autollenado.
    function autofill(d) {
        function put(name, val) {
            var el = q(name);
            if (!el || !val) { return; }
            if (el.value && el.dataset.jgAuto !== '1') { return; }
            el.value = val; el.dataset.jgAuto = '1';
            el.dispatchEvent(new Event('input', {bubbles: true}));
        }
        put('name', d.nombre); put('x_studio_nombre_comercial', d.nombre_comercial); put('vat', d.rfc);
        put('street_name', d.calle); put('street_number', d.num_ext); put('street_number2', d.num_int);
        if (d.regimen) {
            var r = document.querySelector('input[name="l10n_mx_edi_fiscal_regime"][value="' + d.regimen + '"]');
            if (r && !document.querySelector('input[name="l10n_mx_edi_fiscal_regime"]:checked')) { r.checked = true; r.dispatchEvent(new Event('change', {bubbles: true})); }
        }
        if (d.cp) {
            pendingColonia = d.colonia || '';
            var z = q('zip');
            if (z && (!z.value || z.dataset.jgAuto === '1')) {
                z.dataset.jgAuto = '1'; z.value = d.cp;
                z.dispatchEvent(new Event('input', {bubbles: true}));
            }
        }
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

    // CSF: al elegir el archivo se revisa la fecha de emision (mes en curso o mes anterior) y se avisa al momento.
    // ---- CSF / opinion: aviso al elegir el archivo, ayuda de Ale al segundo bloqueo --------------------------------------
    var csfLevel = 0, aleBox = null, aleTimer = null, reruns = [];
    var FILES = [['Constancia Situación Fiscal', 'csf', 'Constancia vigente.'], ['Opinión de cumplimiento', 'opinion', 'Opinión vigente.']];

    function linkify(node, text) {
        node.textContent = '';
        String(text || '').split(/(https?:\/\/\S+)/).forEach(function (part) {
            if (/^https?:\/\//.test(part)) {
                var a = document.createElement('a');
                a.href = part; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.textContent = part;
                node.appendChild(a);
            } else if (part) {
                node.appendChild(document.createTextNode(part));
            }
        });
    }

    function getCookieToken() { try { return localStorage.getItem('jaguen_chat_token') || ''; } catch (e) { return ''; } }

    function applyUnlock(level) {
        if (level <= csfLevel) { return; }
        csfLevel = level;
        FILES.forEach(function (f) {
            var inp = q(f[0]);
            if (!inp) { return; }
            if (f[1] === 'opinion') { inp.removeAttribute('required'); }
            if (f[1] === 'csf') { inp.setAttribute('accept', '.pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png'); }
            if (inp.dataset.jgState !== 'rfcdiff') { inp.setCustomValidity(''); }
        });
        // se vuelve a revisar el archivo ya elegido (ahora sin bloquear fecha/tipo)
        reruns.forEach(function (fn) { fn(); });
        if (aleBox) {
            aleBox.className = 'alert alert-success small mt-2';
            aleBox.textContent = '✓ Ale ya lo solucionó. Vuelve a elegir tu archivo y presiona Enviar. La constancia sí es necesaria (aunque sea foto o no esté actualizada); la opinión ya no es obligatoria. Un asesor te pedirá después los documentos actualizados.';
        }
    }

    function pollUnlock() {
        clearInterval(aleTimer);
        var tries = 0;
        aleTimer = setInterval(function () {
            var token = getCookieToken();
            if (!token || ++tries > 200) { if (tries > 200) { clearInterval(aleTimer); } return; }
            document.cookie = 'jg_chat=' + encodeURIComponent(token) + '; path=/; max-age=7200; SameSite=Lax';
            fetch('/jaguen/docs/unlocked?token=' + encodeURIComponent(token))
                .then(function (r) { return r.json(); })
                .then(function (d) { if (d.unlocked) { applyUnlock(d.level || 1); } })
                .catch(function () { /* se reintenta */ });
        }, 3000);
    }

    var aleAsked = false;
    function askAle(label, d) {
        var g = function (n) { var e = q(n); return e ? (e.value || '').trim() : ''; };
        var pre = {nombre: g('jaguen_contact_name'), empresa: g('name'), correo: g('jaguen_contact_email') || g('email'),
                   telefono: g('jaguen_contact_mobile') || g('phone')};
        var msg = 'Estoy registrándome y el sistema no me deja subir mi ' + label + '. Me dice: "' + (d.mensaje || 'que está mal') + '" ' +
                  (d.detalle || '');
        if (window.jaguenChat) { window.jaguenChat.openWith(pre, msg); }
        pollUnlock();
    }

    function showAle(label, d) {
        var last = q(FILES[1][0]);
        if (!last || csfLevel >= 1) { return; }
        if (!aleBox) {
            aleBox = document.createElement('div');
            var holder = last.closest('.s_website_form_field') || last.parentNode;
            holder.appendChild(aleBox);
        }
        aleBox.className = 'alert alert-info small mt-2';
        aleBox.textContent = '';
        aleBox.appendChild(document.createTextNode('¿Necesitas ayuda con tus documentos? Ale te ayuda para que termines tu registro. '));
        var b = document.createElement('button');
        b.type = 'button'; b.className = 'btn btn-sm btn-primary';
        b.textContent = 'Hablar con Ale';
        b.addEventListener('click', function () { askAle(label, d); });
        aleBox.appendChild(b);
        if (!aleAsked) { aleAsked = true; askAle(label, d); }  // la primera vez entra Ale sola
    }

    function bindCsf(name, tipo, okText) {
        var input = q(name);
        if (!input || input.dataset.jgCsf) { return; }
        input.dataset.jgCsf = '1';
        var box = document.createElement('div');
        box.className = 'small mt-1';
        input.parentNode.appendChild(box);
        function run() {
            input.setCustomValidity('');
            input.dataset.jgState = '';
            box.textContent = '';
            var f = input.files && input.files[0];
            if (!f) { return; }
            var vatNow = q('vat') ? q('vat').value : '';
            var key = f.name + '|' + f.size + '|' + f.lastModified + '|' + vatNow;
            if (input.dataset.jgBusy === key || input.dataset.jgDone === key) { return; }
            input.dataset.jgBusy = key; input.dataset.jgLastVat = vatNow;
            if (csfLevel >= 1 && tipo === 'csf' && /^image\//.test(f.type)) {
                box.className = 'small mt-1 text-muted';
                box.textContent = 'Recibimos tu foto; un asesor la revisará y te pedirá la constancia en PDF si hace falta.';
                return;
            }
            box.className = 'small mt-1 text-muted';
            box.textContent = 'Revisando tu archivo…';
            var fd = new FormData();
            fd.append('archivo', f);
            fd.append('tipo', tipo);
            var vat = q('vat');
            fd.append('rfc', vat ? vat.value : '');
            fd.append('csrf_token', (window.odoo && window.odoo.csrf_token) || '');
            fetch('/jaguen/csf/check', {method: 'POST', body: fd})
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    input.dataset.jgDone = key; input.dataset.jgBusy = '';
                    input.dataset.jgState = d.estado;
                    if (tipo === 'csf' && d.datos && d.datos.rfc) { autofill(d.datos); }
                    var blocking = ['old', 'future', 'notcsf', 'notpdf', 'rfcdiff'].indexOf(d.estado) >= 0;
                    // Con el envio desbloqueado por Ale solo el RFC distinto sigue bloqueando.
                    if (blocking && csfLevel >= 1 && d.estado !== 'rfcdiff') { blocking = false; }
                    if (blocking) {
                        box.className = 'small mt-1 text-danger fw-bold';
                        linkify(box, d.mensaje);
                        input.setCustomValidity(d.mensaje);
                        showAle(tipo === 'csf' ? 'constancia' : 'opinión de cumplimiento', d);
                    } else if (d.estado === 'ok') {
                        box.className = 'small mt-1 text-success';
                        box.textContent = '✓ ' + okText + (tipo === 'csf' && d.datos && d.datos.rfc ? ' Llenamos tus datos con ella: por favor revísalos.' : '');
                    } else {
                        box.className = 'small mt-1 text-muted';
                        linkify(box, csfLevel >= 1 ? '' : (d.mensaje || ''));
                    }
                })
                .catch(function () { box.textContent = ''; input.dataset.jgBusy = ''; });
        }
        input.addEventListener('change', run);
        reruns.push(function () { if (input.files && input.files[0]) { run(); } });
        var vatEl = q('vat');
        if (vatEl) {
            vatEl.addEventListener('change', function (ev) {
                if (ev.isTrusted && input.files && input.files[0] && vatEl.value !== input.dataset.jgLastVat) { run(); }
            });
        }
    }

    // Compra personal: se esconden y dejan de ser obligatorios RFC, regimen, CSF, opinion y contacto comprador.
    function bindPersonal() {
        var chk = q('jaguen_personal');
        if (!chk || chk.dataset.jgBound) { return; }
        chk.dataset.jgBound = '1';
        function apply() {
            var hide = chk.checked;
            document.querySelectorAll('.jg-personal-hide').forEach(function (blk) {
                blk.classList.toggle('d-none', hide);
                blk.querySelectorAll('input, select, textarea').forEach(function (inp) {
                    if (inp.dataset.jgReqP === undefined) { inp.dataset.jgReqP = inp.required ? '1' : '0'; }
                    inp.required = hide ? false : inp.dataset.jgReqP === '1';
                    inp.disabled = hide;
                    if (hide) { inp.setCustomValidity(''); }
                });
            });
        }
        // El correo de arriba es "Correo para facturas y REP" en empresas; en compra personal es solo el correo de la persona.
        var emailEl = q('email'), emailBlk = emailEl && emailEl.closest('.s_website_form_field');
        var lab = emailBlk && emailBlk.querySelector('.s_website_form_label_content');
        var help = emailBlk && emailBlk.querySelector('.s_website_form_field_description');
        var labOrig = lab ? lab.textContent : '';
        function apply2() {
            apply();
            if (lab) { lab.textContent = chk.checked ? 'Correo electrónico' : labOrig; }
            if (help) { help.classList.toggle('d-none', chk.checked); }
        }
        chk.addEventListener('change', apply2);
        apply2();
    }

    // Estado del formulario para Ale (solo nombres de campos; nunca lo que el cliente escribio).
    window.jaguenChatContext = function () {
        var root = q('name') && q('name').closest('form');
        if (!root) { return ''; }
        var pend = [], errs = [], done = 0, seen = {};
        root.querySelectorAll('.s_website_form_field').forEach(function (blk) {
            if (!(blk.offsetWidth || blk.offsetHeight)) { return; }
            var labEl = blk.querySelector('.s_website_form_label_content');
            var label = labEl ? labEl.textContent.trim() : '';
            var inputs = blk.querySelectorAll('input:not([type=hidden]):not(.jg-skip), select, textarea');
            if (!label || !inputs.length || seen[label]) { return; }
            var req = !!blk.querySelector('[required]');
            if (!req) { return; }
            var filled = false, bad = '';
            var first = inputs[0];
            if (first.type === 'radio') { filled = !!blk.querySelector('input[type=radio]:checked'); }
            else if (first.type === 'file') { filled = !!(first.files && first.files.length); bad = first.validationMessage || ''; }
            else if (first.type === 'checkbox') { filled = first.checked; }
            else {
                var colSel = blk.querySelector('.jg-colonia-sel');
                var val = colSel && colSel.offsetHeight ? colSel.value : first.value;
                filled = !!(val && val.trim());
                if (first.disabled) { return; }
                bad = filled ? (first.validationMessage || '') : '';
            }
            seen[label] = 1;
            if (!filled) { pend.push(label); } else if (bad) { errs.push(label + ' (' + bad.slice(0, 90) + ')'); } else { done += 1; }
        });
        var out = 'Obligatorios pendientes: ' + (pend.length ? pend.join(', ') : 'ninguno') + '.';
        if (errs.length) { out += ' Con error: ' + errs.join('; ') + '.'; }
        return out + ' Ya completos: ' + done + '.';
    };

    function init() {
        bindPersonal();
        FILES.forEach(function (f) { bindCsf(f[0], f[1], f[2]); });
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
