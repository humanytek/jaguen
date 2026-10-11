/* Asistente virtual JAGUEN: widget de chat (JS plano, sin dependencias). */
(function () {
    'use strict';
    var path = location.pathname;
    // No estorba en backend, pago ni checkout.
    if (/^\/(web|odoo|payment|website\/|shop\/(payment|checkout|confirmation|address|l10n_mx))/.test(path)) { return; }
    if (document.getElementById('jaguen_chat_root')) { return; }

    var STORE = 'jaguen_chat_token';
    var token = null, lastId = 0, state = 'ai', opened = false, started = false, busy = false, timer = null;

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

    var root = el('div'); root.id = 'jaguen_chat_root';
    var btn = el('button', 'jgc-btn', '¿Te ayudamos?'); btn.type = 'button';
    btn.setAttribute('aria-label', 'Abrir el chat de JAGUEN');
    var panel = el('div', 'jgc-panel jgc-hidden');
    var head = el('div', 'jgc-head');
    var title = el('span', 'jgc-title', 'JAGUEN'); head.appendChild(title);
    var close = el('button', 'jgc-close', '×'); close.type = 'button'; close.setAttribute('aria-label', 'Cerrar');
    head.appendChild(close);
    var list = el('div', 'jgc-list');
    var note = el('div', 'jgc-note');
    note.appendChild(document.createTextNode('No compartas datos bancarios ni contraseñas. Al escribir aceptas nuestro '));
    var privacy = el('a', null, 'Aviso de Privacidad'); privacy.href = '/aviso-de-privacidad'; privacy.target = '_blank'; privacy.rel = 'noopener';
    note.appendChild(privacy); note.appendChild(document.createTextNode('.'));
    var form = el('form', 'jgc-form');
    var input = el('input', 'jgc-input'); input.type = 'text'; input.maxLength = 600;
    input.placeholder = 'Escribe tu mensaje...'; input.autocomplete = 'off';
    var send = el('button', 'jgc-send', 'Enviar'); send.type = 'submit';
    form.appendChild(input); form.appendChild(send);
    panel.appendChild(head); panel.appendChild(list); panel.appendChild(note); panel.appendChild(form);
    root.appendChild(btn); root.appendChild(panel);

    function linkify(container, text) {
        var parts = String(text).split(/(https?:\/\/[^\s]+)/g);
        parts.forEach(function (p) {
            if (/^https?:\/\//.test(p)) {
                var m = p.match(/^(.*?)([.,;:!?)]*)$/);
                var url = m[1], tail = m[2], host = '';
                try { host = new URL(url).hostname; } catch (e) { host = ''; }
                if (/(^|\.)jaguen\.com$/.test(host)) {
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

    function start() {
        if (started) { return; }
        started = true;
        rpc('/jaguen/chat/start', {token: lsGet()}).then(function (r) {
            token = r.token; lsSet(token); state = r.state;
            if (r.name) { title.textContent = r.name + ' · JAGUEN'; }
            bubble('bot', r.greeting);
            addMessages(r.messages);
            if (state === 'human') { startPolling(); }
        }).catch(function () {
            started = false;
            bubble('sys', 'No se pudo iniciar el chat. Intenta de nuevo en un momento.');
        });
    }

    function openPanel() {
        opened = true;
        panel.classList.remove('jgc-hidden'); btn.classList.add('jgc-hidden');
        start();
        if (state === 'human') { startPolling(); }
        setTimeout(function () { input.focus(); }, 50);
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
