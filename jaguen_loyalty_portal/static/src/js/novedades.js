(function () {
    var KEY = 'jgNovedadPuntosVisto';
    function stored() { try { return window.sessionStorage.getItem(KEY); } catch (e) { return null; } }
    function store() { try { window.sessionStorage.setItem(KEY, '1'); } catch (e) { /* sin sessionStorage */ } }
    function storedLocal() { try { return window.localStorage.getItem(KEY); } catch (e) { return null; } }
    function storeLocal() { try { window.localStorage.setItem(KEY, '1'); } catch (e) { /* sin localStorage */ } }
    function init() {
        // Ventana "Nuevo": sale UNA sola vez por persona. Se marca como vista en el servidor en cuanto se muestra
        // (y se guarda tambien en el navegador por si falla la red).
        var modal = document.querySelector('.jg-novedad-modal');
        if (modal && !stored() && !storedLocal()) {
            modal.style.display = 'flex';
            storeLocal(); store();
            fetch('/jaguen/novedad/visto', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({jsonrpc: '2.0', method: 'call', params: {page: 'puntos_popup'}}),
            }).catch(function () {});
            var close = function () { store(); modal.style.display = 'none'; };
            modal.querySelectorAll('[data-jg-close]').forEach(function (el) { el.addEventListener('click', close); });
            modal.addEventListener('click', function (ev) { if (ev.target === modal) { close(); } });
            document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') { close(); } });
        }
        // Ya entro a Mis Puntos: se apaga su aviso
        var mark = document.querySelector('.jg-novedad-mark');
        if (mark) {
            setTimeout(function () {
                fetch('/jaguen/novedad/visto', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({jsonrpc: '2.0', method: 'call', params: {page: mark.dataset.page}}),
                }).catch(function () {});
            }, 2500);
        }
    }
    // Odoo 18 carga este archivo "tarde" (bundle lazy): puede que la pagina ya haya terminado de cargar.
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
