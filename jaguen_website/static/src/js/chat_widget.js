/* Chat de Jaguen: formulario previo, pantalla de conexion y conversacion (JS plano, sin dependencias). */
(function () {
    'use strict';
    var path = location.pathname;
    // Solo se oculta en el backend: en el sitio publico (incluido el checkout) siempre esta disponible.
    if (/^\/(web|odoo|website\/)/.test(path)) { return; }
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

    // ---------- agente (nombre + foto) ----------
    var BASE_IMG = '/jaguen_website/static/src/img/';
    var PHOTOS = {ale: 'agent_ale.jpg', monica: 'agent_monica.jpg', andrea: 'agent_andrea.jpg', ivan: 'agent_ivan.jpg'};
    function slug(n) { return (n || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim(); }
    function avatar(cls, name) {
        var a = el('span', cls), f = PHOTOS[slug(name)];
        if (f) { var im = el('img'); im.src = BASE_IMG + f; im.alt = name; im.width = 64; im.height = 64; a.appendChild(im); }
        else { a.textContent = (name || 'J').charAt(0); }
        return a;
    }
    // ---------- estructura ----------
    var root = el('div'); root.id = 'jaguen_chat_root';
    var btn = el('button', 'jgc-btn'); btn.type = 'button';
    btn.setAttribute('aria-label', 'Abrir el chat de Jaguen');
    var panel = el('div', 'jgc-panel jgc-hidden');
    var head = el('div', 'jgc-head');
    var headAv = el('span', 'jgc-hav'); var title = el('span', 'jgc-title', 'Jaguen');
    var headWho = el('span', 'jgc-who'); headWho.appendChild(headAv); headWho.appendChild(title); head.appendChild(headWho);
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
    var connectAv = el('div', 'jgc-connect-av'); connectView.appendChild(connectAv);
    var connectT = el('div', 'jgc-connect-t', 'Conectándote con quien te atenderá…'); connectView.appendChild(connectT);
    connectView.appendChild(el('div', 'jgc-connect-s', 'Tiempo de espera: menos de 60 segundos'));

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
        if (name) {
            title.textContent = name + ' · Jaguen';
            headAv.textContent = ''; headAv.appendChild(avatar('jgc-avatar jgc-avatar-sm', name));
        }
        showView('chat');
        addMessages(msgs);
        if (state === 'human') { startPolling(); }
        setTimeout(function () { input.focus(); }, 50);
        setTimeout(function () { if (typeof flushPending === 'function') { flushPending(); } }, 300);
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
            // Pantalla de conexion: 8 segundos fijos antes de que entre quien atiende.
            connecting = true;
            connectT.textContent = 'Conectándote con ' + (r.name || 'quien te atenderá') + '…';
            connectAv.textContent = ''; connectAv.appendChild(avatar('jgc-avatar jgc-avatar-lg', r.name));
            showView('connect');
            var wait = 8000;
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

    // API para abrir el chat desde otra pagina (Registrate): precarga el formulario y manda un primer mensaje.
    var pendingMsg = null;
    window.jaguenChat = {
        openWith: function (pre, msg) {
            pendingMsg = msg || null;
            openPanel();
            if (token && started) { flushPending(); return; }
            setTimeout(function () {
                if (pre && !token) {
                    fName.value = pre.nombre || fName.value; fCompany.value = pre.empresa || fCompany.value;
                    fEmail.value = pre.correo || fEmail.value; fPhone.value = pre.telefono || fPhone.value;
                    if (fName.value && fEmail.value && fPhone.value.replace(/\D/g, '').length >= 10) {
                        form0.dispatchEvent(new Event('submit', {cancelable: true}));
                    }
                }
            }, 400);
        }
    };
    function flushPending() {
        if (!pendingMsg || !token || connecting) { return; }
        var m = pendingMsg; pendingMsg = null;
        input.value = m;
        form.dispatchEvent(new Event('submit', {cancelable: true}));
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

    function buildCard(list) {
        // Las tres juntas; quien atiende se asigna hasta que el visitante inicia la conversacion.
        var names = (list && list.length) ? list.filter(function (n) { return PHOTOS[slug(n)]; }) : ['Andrea', 'Mónica', 'Iván', 'Ale'];
        if (!names.length) { names = ['Andrea', 'Mónica', 'Iván', 'Ale']; }
        var group = el('span', 'jgc-group');
        names.slice(0, 4).forEach(function (n) { group.appendChild(avatar('jgc-avatar', n)); });
        btn.appendChild(group);
        var tx = el('span', 'jgc-btn-tx');
        tx.appendChild(el('span', 'jgc-btn-name', '¿Te ayudamos?'));
        tx.appendChild(el('span', 'jgc-btn-sub', 'Asistente virtual de Jaguen'));
        tx.appendChild(el('span', 'jgc-btn-cta', 'Escríbenos aquí'));
        btn.appendChild(tx);
        btn.setAttribute('aria-label', 'Abrir el chat de Jaguen');
    }
    function mount(list) { buildCard(list); document.body.appendChild(root); }
    function mountWhenReady(list) { if (document.body) { mount(list); } else { document.addEventListener('DOMContentLoaded', function () { mount(list); }); } }

    // Solo se muestra si el asistente esta activo (hay llave configurada). El estado se recuerda 10 minutos.
    var cached = null;
    try { cached = JSON.parse(sessionStorage.getItem('jaguen_chat_ok') || 'null'); } catch (e) { cached = null; }
    if (cached && Date.now() - cached.t < 600000) {
        if (cached.v) { mountWhenReady(cached.a); }
    } else {
        rpc('/jaguen/chat/status', {}).then(function (r) {
            try { sessionStorage.setItem('jaguen_chat_ok', JSON.stringify({v: !!r.enabled, a: r.agents || [], t: Date.now()})); } catch (e) { /* ok */ }
            if (r.enabled) { mountWhenReady(r.agents || []); }
        }).catch(function () { /* sin chat si falla */ });
    }
})();
