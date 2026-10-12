/* Chat de Jaguen: formulario previo, pantalla de conexion y conversacion (JS plano, sin dependencias). */
(function () {
    'use strict';
    var path = location.pathname;
    // No estorba en backend, pago ni checkout.
    if (/^\/(web|odoo|payment|website\/|shop\/(payment|checkout|confirmation|address|l10n_mx))/.test(path)) { return; }
    if (document.getElementById('jaguen_chat_root')) { return; }

    var STORE = 'jaguen_chat_token';
    var token = null, lastId = 0, state = 'ai', opened = false, started = false, busy = false, timer = null;
    var connecting = false, connectDone = null;

    function lsGet() { try { return localStorage.getItem(STORE); } catch (e) { return null; } }
    function lsSet(v) { try { localStorage.setItem(STORE, v); } catch (e) { /* sin almacenamiento */ } }

    function rpc(url, params) {
        return fetch(url, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({jsonrpc: '2.0', method: 'call', params: params || {}}),
        }).then(function (r) { return r.json(); }).then(function (j) {
            if (j.error) { throw new Error('rpc'); }
            return j.result;
        });
    }

    function el(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) { e.className = cls; }
        if (text) { e.textContent = text; }
        return e;
    }

    // ---------- estructura ----------
    var root = el('div'); root.id = 'jaguen_chat_root';
    var btn = el('button', 'jgc-btn', '¿Te ayudamos?'); btn.type = 'button';
    btn.setAttribute('aria-label', 'Abrir el chat de Jaguen');
    var panel = el('div', 'jgc-panel jgc-hidden');
    var head = el('div', 'jgc-head');
    var title = el('span', 'jgc-title', 'Jaguen'); head.appendChild(title);
    var close = el('button', 'jgc-close', '×'); close.type = 'button'; close.setAttribute('aria-label', 'Cerrar');
    head.appendChild(close);

    function privacyNote() {
        var note = el('div', 'jgc-note');
        note.appendChild(document.createTextNode('No compartas datos bancarios ni contraseñas. Al escribir aceptas nuestro '));
        var a = el('a', null, 'Aviso de Privacidad'); a.href = '/aviso-de-privacidad'; a.target = '_blank'; a.rel = 'noopener';
        note.appendChild(a); note.appendChild(document.createTextNode('.'));
        return note;
    }

    // vista 1: formulario previo
    var formView = el('div', 'jgc-view jgc-hidden');
    var form0 = el('form', 'jgc-prechat'); form0.noValidate = true;
    form0.appendChild(el('div', 'jgc-lead', 'Compártenos tus datos para darte un mejor servicio.'));
    function field(name, label, type, ph) {
        var wrap = el('div', 'jgc-field');
        wrap.appendChild(el('label', null, label));
        var i = el('input'); i.type = type; i.name = name; i.placeholder = ph || ''; i.maxLength = 80; i.autocomplete = 'off';
        wrap.appendChild(i);
        var err = el('div', 'jgc-err'); err.setAttribute('data-err', name); wrap.appendChild(err);
        form0.appendChild(wrap);
        return i;
    }
    var fName = field('nombre', 'Nombre', 'text', 'Tu nombre');
    var fCompany = field('empresa', 'Empresa', 'text', 'Nombre de tu empresa');
    var fEmail = field('correo', 'Correo', 'email', 'correo@empresa.com');
    var fPhone = field('telefono', 'Teléfono', 'tel', '10 dígitos');
    var personalWrap = el('label', 'jgc-check');
    var fPersonal = el('input'); fPersonal.type = 'checkbox'; fPersonal.name = 'personal';
    personalWrap.appendChild(fPersonal); personalWrap.appendChild(document.createTextNode(' Es compra personal (no tengo empresa)'));
    form0.appendChild(personalWrap);
    var hp = el('input'); hp.type = 'text'; hp.name = 'hp'; hp.tabIndex = -1; hp.autocomplete = 'off';
    hp.setAttribute('aria-hidden', 'true'); hp.className = 'jgc-hp'; form0.appendChild(hp);
    var formMsg = el('div', 'jgc-err jgc-formmsg'); form0.appendChild(formMsg);
    var startBtn = el('button', 'jgc-send jgc-start', 'Iniciar chat'); startBtn.type = 'submit'; form0.appendChild(startBtn);
    var priv0 = el('div', 'jgc-note'); priv0.appendChild(document.createTextNode('Al continuar aceptas nuestro '));
    var a0 = el('a', null, 'Aviso de Privacidad'); a0.href = '/aviso-de-privacidad'; a0.target = '_blank'; a0.rel = 'noopener';
    priv0.appendChild(a0); priv0.appendChild(document.createTextNode('.'));
    formView.appendChild(form0); formView.appendChild(priv0);

    // vista 2: conectando
    var connectView = el('div', 'jgc-view jgc-connect jgc-hidden');
    connectView.appendChild(el('div', 'jgc-spinner'));
    connectView.appendChild(el('div', 'jgc-connect-t', 'Conectándote con quien te atenderá…'));
    connectView.appendChild(el('div', 'jgc-connect-s', 'Tiempo de espera: menos de 20 segundos'));

    // vista 3: conversacion
    var chatView = el('div', 'jgc-view jgc-chatview jgc-hidden');
    var list = el('div', 'jgc-list');
    var form = el('form', 'jgc-form');
    var input = el('input', 'jgc-input'); input.type = 'text'; input.maxLength = 600;
    input.placeholder = 'Escribe tu mensaje...'; input.autocomplete = 'off';
    var send = el('button', 'jgc-send', 'Enviar'); send.type = 'submit';
    form.appendChild(input); form.appendChild(send);
    chatView.appendChild(list); chatView.appendChild(privacyNote()); chatView.appendChild(form);

    panel.appendChild(head); panel.appendChild(formView); panel.appendChild(connectView); panel.appendChild(chatView);
    root.appendChild(btn); root.appendChild(panel);

    function showView(name) {
        formView.classList.toggle('jgc-hidden', name !== 'form');
        connectView.classList.toggle('jgc-hidden', name !== 'connect');
        chatView.classList.toggle('jgc-hidden', name !== 'chat');
    }

    // ---------- conversacion ----------
    function linkify(container, text) {
        var parts = String(text).split(/(https?:\/\/[^\s]+)/g);
        parts.forEach(function (p) {
            if (/^https?:\/\//.test(p)) {
                var m = p.match(/^(.*?)([.,;:!?)]*)$/);
                var url = m[1], tail = m[2], host = '';
                try { host = new URL(url).hostname; } catch (e) { host = ''; }
                if (/(^|\.)jaguen\.com$/.test(host) || host === location.hostname) {
                    var a = el('a', null, url); a.href = url; a.target = '_blank'; a.rel = 'noopener';
                    container.appendChild(a);
                    if (tail) { container.appendChild(document.createTextNode(tail)); }
                } else {
                    container.appendChild(document.createTextNode(p));
                }
            } else if (p) {
                container.appendChild(document.createTextNode(p));
            }
        });
    }

    function bubble(role, text) {
        var b = el('div', 'jgc-msg jgc-' + role);
        linkify(b, text);
        list.appendChild(b);
        list.scrollTop = list.scrollHeight;
        return b;
    }

    function addMessages(msgs) {
        (msgs || []).forEach(function (m) {
            bubble(m.role === 'staff' ? 'staff' : 'bot', m.text);
            if (m.id > lastId) { lastId = m.id; }
        });
    }

    function setState(s) {
        if (s === 'human' && state !== 'human') {
            bubble('sys', 'Te atiende una persona del equipo. Responderá por este mismo chat.');
        }
        state = s;
        if (state === 'human' && opened) { startPolling(); }
    }

    function poll() {
        if (!token || !opened || state !== 'human') { return; }
        rpc('/jaguen/chat/poll', {token: token, after_id: lastId}).then(function (r) {
            addMessages(r.messages);
            if (r.state && r.state !== 'human') { state = r.state; stopPolling(); }
        }).catch(function () { /* se reintenta */ });
    }
    function startPolling() { if (!timer) { timer = setInterval(poll, 4000); } }
    function stopPolling() { if (timer) { clearInterval(timer); timer = null; } }

    function enterChat(name, msgs) {
        if (name) { title.textContent = name + ' · Jaguen'; }
        showView('chat');
        addMessages(msgs);
        if (state === 'human') { startPolling(); }
        setTimeout(function () { input.focus(); }, 50);
    }

    function start() {
        if (started) { return; }
        started = true;
        rpc('/jaguen/chat/start', {token: lsGet()}).then(function (r) {
            if (r.need_form) { showView('form'); fName.focus(); return; }
            token = r.token; lsSet(token); state = r.state;
            if (r.greeting) { bubble('bot', r.greeting); }
            enterChat(r.name, r.messages);
        }).catch(function () {
            started = false;
            showView('chat');
            bubble('sys', 'No se pudo iniciar el chat. Intenta de nuevo en un momento.');
        });
    }

    // ---------- formulario ----------
    fPersonal.addEventListener('change', function () {
        fCompany.disabled = fPersonal.checked;
        if (fPersonal.checked) { fCompany.value = ''; }
    });

    function setErrors(errs) {
        Array.prototype.forEach.call(form0.querySelectorAll('[data-err]'), function (d) {
            d.textContent = (errs && errs[d.getAttribute('data-err')]) || '';
        });
    }

    form0.addEventListener('submit', function (ev) {
        ev.preventDefault();
        if (busy) { return; }
        var data = {nombre: fName.value.trim(), empresa: fCompany.value.trim(), correo: fEmail.value.trim(),
                    telefono: fPhone.value.trim(), personal: fPersonal.checked, hp: hp.value};
        var errs = {};
        if (data.nombre.length < 2) { errs.nombre = 'Escribe tu nombre.'; }
        if (!data.personal && data.empresa.length < 2) { errs.empresa = 'Escribe tu empresa o marca "Es compra personal".'; }
        if (!/^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(data.correo)) { errs.correo = 'Escribe un correo válido.'; }
        if (data.telefono.replace(/\D/g, '').length < 10) { errs.telefono = 'Escribe un teléfono de 10 dígitos.'; }
        setErrors(errs); formMsg.textContent = '';
        if (Object.keys(errs).length) { return; }
        busy = true; startBtn.disabled = true;
        rpc('/jaguen/chat/start_form', data).then(function (r) {
            if (r.errors) { setErrors(r.errors); return; }
            if (r.error) {
                formMsg.textContent = (r.error === 'limit')
                    ? 'Por hoy ya alcanzaste el límite de solicitudes. Escríbenos desde la página de contacto.'
                    : 'No se pudo iniciar el chat en este momento. Intenta más tarde.';
                return;
            }
            token = r.token; lsSet(token); state = r.state; started = true;
            // Pantalla de conexion: entre 6 y 10 segundos antes de que entre quien atiende.
            connecting = true; showView('connect');
            var wait = 6000 + Math.floor(Math.random() * 4000);
            connectDone = setTimeout(function () { connecting = false; enterChat(r.name, r.messages); }, wait);
        }).catch(function () {
            formMsg.textContent = 'No se pudo enviar el formulario. Intenta de nuevo.';
        }).then(function () { busy = false; startBtn.disabled = false; });
    });

    // ---------- abrir / cerrar / enviar ----------
    function openPanel() {
        opened = true;
        panel.classList.remove('jgc-hidden'); btn.classList.add('jgc-hidden');
        if (connecting) { showView('connect'); } else { start(); }
        if (state === 'human') { startPolling(); }
    }
    function closePanel() {
        opened = false; stopPolling();
        panel.classList.add('jgc-hidden'); btn.classList.remove('jgc-hidden');
    }

    btn.addEventListener('click', openPanel);
    close.addEventListener('click', closePanel);
    form.addEventListener('submit', function (ev) {
        ev.preventDefault();
        var text = input.value.trim();
        if (!text || busy || !token) { return; }
        busy = true; input.value = ''; send.disabled = true;
        bubble('user', text);
        var typing = bubble('sys', 'Escribiendo...');
        rpc('/jaguen/chat/send', {token: token, text: text}).then(function (r) {
            typing.remove();
            if (r.user_message_id && r.user_message_id > lastId) { lastId = r.user_message_id; }
            addMessages(r.messages);
            setState(r.state);
        }).catch(function () {
            typing.remove();
            bubble('sys', 'No se pudo enviar el mensaje. Intenta de nuevo.');
        }).then(function () { busy = false; send.disabled = false; input.focus(); });
    });

    function mount() { document.body.appendChild(root); }
    function mountWhenReady() { if (document.body) { mount(); } else { document.addEventListener('DOMContentLoaded', mount); } }

    // Solo se muestra si el asistente esta activo (hay llave configurada). El estado se recuerda 10 minutos.
    var cached = null;
    try { cached = JSON.parse(sessionStorage.getItem('jaguen_chat_ok') || 'null'); } catch (e) { cached = null; }
    if (cached && Date.now() - cached.t < 600000) {
        if (cached.v) { mountWhenReady(); }
    } else {
        rpc('/jaguen/chat/status', {}).then(function (r) {
            try { sessionStorage.setItem('jaguen_chat_ok', JSON.stringify({v: !!r.enabled, t: Date.now()})); } catch (e) { /* ok */ }
            if (r.enabled) { mountWhenReady(); }
        }).catch(function () { /* sin chat si falla */ });
    }
})();
