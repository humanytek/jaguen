(function () {
    var KEY = 'jgNovedadPuntosVisto';
    function stored() { try { return window.sessionStorage.getItem(KEY); } catch (e) { return null; } }
    function store() { try { window.sessionStorage.setItem(KEY, '1'); } catch (e) { /* sin sessionStorage */ } }
    function init() {
        // Ventana "Nuevo": sale una sola vez por visita (si la cierran o entran, no vuelve a salir en esa visita)
        var modal = document.querySelector('.jg-novedad-modal');
        if (modal && !stored()) {
            modal.style.display = 'flex';
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
