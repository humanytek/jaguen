/** @odoo-module **/
// Columnas opcionales de las listas: se guardan por usuario en el servidor y con una llave estable.
// Odoo las guarda solo en localStorage y su llave incluye la lista de campos de la vista, asi que se pierden al
// cambiar de navegador/equipo o cuando una actualizacion agrega o quita un campo de esa pantalla.
import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { ListRenderer } from "@web/views/list/list_renderer";
import { user } from "@web/core/user";
import { onMounted, onPatched, onWillUnmount } from "@odoo/owl";
import { ProductLabelSectionAndNoteListRender } from "@account/components/product_label_section_and_note_field/product_label_section_and_note_field";

const COLUMNAS_PRODUCTO = ["product_id", "product_template_id", "product_variant_id"];

// Ancho natural de cada columna (lo que necesita su contenido sin cortarse): se lo pedimos al propio navegador, dejando
// por un instante que la tabla se acomode sola con todo en una linea. No se alcanza a pintar nada entre medir y volver.
function medirNaturales(table, heads) {
    table.classList.add("jg-medir");
    const natural = heads.map((th) => Math.ceil(th.getBoundingClientRect().width));
    table.classList.remove("jg-medir");
    return natural;
}

function applyLineas(table, heads, avail, saved) {
    // Mientras se edita una linea no se vuelve a medir (los campos de captura miden distinto y la tabla "brincaria")
    let natural = table._jgNatural;
    if (!natural || natural.length !== heads.length || !table.querySelector("tr.o_selected_row")) {
        natural = medirNaturales(table, heads);
        table._jgNatural = natural;
    }
    const ancho = new Map();
    let fijos = 0;
    let ajustadas = 0;
    const columnasProducto = [];
    const columnasNombre = [];
    heads.forEach((th, i) => {
        const nombre = th.dataset.name;
        if (nombre && COLUMNAS_PRODUCTO.includes(nombre)) {
            columnasProducto.push(th);
            return;
        }
        if (nombre === "name") {
            columnasNombre.push(th);
            return;
        }
        let px;
        if (!nombre || nombre === "sequence") {
            // asa para mover la linea, iconos y bote de basura: su ancho ya lo fijo Odoo o el codigo de arriba
            px = Math.ceil(parseFloat(th.style.width) || th.getBoundingClientRect().width);
            if (th.classList.contains("o_list_actions_header") || th.classList.contains("o_list_controller")) {
                px = Math.max(px, 40);
            }
            fijos += px;
        } else {
            const need = (natural[i] || 0) + 14;   // + lugar de la flechita de ordenar
            px = Math.ceil(Math.min(Math.max(need, 44), 230));
            ajustadas += px;
        }
        ancho.set(th, px);
    });
    const resto = avail - fijos - ajustadas;
    // Lo unico que el usuario puede mover es la raya entre Producto y Descripcion: se guarda como proporcion.
    let proporcion = 0.45;
    if (saved && saved.w) {
        const p = COLUMNAS_PRODUCTO.map((n) => saved.w[n]).find((w) => w);
        const n = saved.w.name;
        if (p && n) {
            proporcion = Math.min(0.8, Math.max(0.2, p / (p + n)));
        }
    }
    const MIN_PRODUCTO = 110;
    const MIN_NOMBRE = 140;
    let producto = 0;
    let nombre = 0;
    if (columnasProducto.length && columnasNombre.length) {
        if (resto >= MIN_PRODUCTO + MIN_NOMBRE) {
            producto = Math.max(MIN_PRODUCTO, Math.floor(resto * proporcion));
            nombre = Math.floor(resto - producto);
        } else {
            producto = MIN_PRODUCTO;
            nombre = MIN_NOMBRE;
        }
    } else if (columnasProducto.length) {
        producto = Math.max(MIN_PRODUCTO, Math.floor(resto));
    } else if (columnasNombre.length) {
        nombre = Math.max(MIN_NOMBRE, Math.floor(resto));
    }
    columnasProducto.forEach((th) => ancho.set(th, Math.floor(producto / columnasProducto.length)));
    columnasNombre.forEach((th) => ancho.set(th, Math.floor(nombre / columnasNombre.length)));
    let total = 0;
    for (const th of heads) {
        const px = ancho.get(th);
        if (px === undefined) {
            continue;
        }
        total += px;
        if (Math.abs(parseFloat(th.style.width || 0) - px) >= 1) {
            th.style.width = `${px}px`;
        }
    }
    if (table.style.tableLayout !== "fixed") {
        table.style.tableLayout = "fixed";
    }
    const tablaPx = `${Math.floor(Math.max(avail, total))}px`;
    if (table.style.width !== tablaPx) {
        table.style.width = tablaPx;
    }
}

const jaguenColsService = {
    dependencies: ["orm"],
    async start(env, { orm }) {
        let data = {};
        let timer = null;
        const uid = user && user.userId;
        if (uid) {
            try {
                const rows = await orm.read("res.users", [uid], ["x_jaguen_cols"]);
                data = JSON.parse((rows && rows[0] && rows[0].x_jaguen_cols) || "{}") || {};
            } catch (e) {
                data = {};
            }
        }
        const flush = () => {
            if (!uid) {
                return;
            }
            orm.write("res.users", [uid], { x_jaguen_cols: JSON.stringify(data) }).catch(() => {});
        };
        return {
            get(key) {
                return data[key];
            },
            set(key, value) {
                if (data[key] === value) {
                    return;
                }
                data[key] = value;
                clearTimeout(timer);
                timer = setTimeout(flush, 600);
            },
        };
    },
};
registry.category("services").add("jaguen_cols", jaguenColsService);

patch(ListRenderer.prototype, {
    // Llave estable: modelo + vista (+ campo si es una lista anidada). Sin la lista de campos.
    createViewKey() {
        const nested = this.props.nestedKeyOptionalFieldsData;
        const parts = nested
            ? [nested.model, nested.viewMode, this.env.config.viewId, nested.field, "list"]
            : [this.props.list.resModel, "list", this.env.config.viewId];
        return parts.join(",");
    },

    computeOptionalActiveFields() {
        const svc = this.env.services.jaguen_cols;
        const saved = svc ? svc.get(this.keyOptionalFields) : undefined;
        if (saved === undefined) {
            return super.computeOptionalActiveFields(...arguments);
        }
        const names = saved ? saved.split(",") : [];
        const result = {};
        for (const col of this.allColumns) {
            if (col.type === "field" && col.optional) {
                result[col.name] = names.includes(col.name);
            }
        }
        return result;
    },

    saveOptionalActiveFields() {
        super.saveOptionalActiveFields(...arguments);
        const svc = this.env.services.jaguen_cols;
        if (svc) {
            svc.set(
                this.keyOptionalFields,
                Object.keys(this.optionalActiveFields)
                    .filter((name) => this.optionalActiveFields[name])
                    .join(",")
            );
        }
    },
});

// Lineas de ventas, compras y facturas: Odoo esconde la columna "Descripcion"/"Etiqueta" cuando "Producto" esta visible
// (las funde en una sola celda). Aqui, si el usuario tiene prendidas las dos, se muestran como columnas separadas.
patch(ProductLabelSectionAndNoteListRender.prototype, {
    getActiveColumns(list) {
        const cols = super.getActiveColumns(list);
        const productCol = cols.find((c) => this.productColumns.includes(c.name));
        const labelCol = this.allColumns && this.allColumns.find((c) => c.name === "name");
        if (!productCol || !labelCol || !this.optionalActiveFields || this.optionalActiveFields.name === false) {
            return cols;
        }
        const labelActive = labelCol.optional ? this.optionalActiveFields.name : true;
        if (!labelActive) {
            return cols;
        }
        list.records.forEach((record) => (record.columnIsProductAndLabel = false));
        const result = [];
        for (const c of this.allColumns) {
            if (cols.includes(c) || c === labelCol) {
                result.push(c);
            }
        }
        return result;
    },
});

// Ancho de las columnas: Odoo lo pierde al recargar. Se guarda por usuario y por lista (misma llave estable que las
// columnas opcionales). Se aplica encima del ancho que calcula Odoo despues de cada pintado de la lista.
patch(ListRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        const widthKey = () => "w|" + this.keyOptionalFields;
        const applyReal = () => {
            const table = this.tableRef && this.tableRef.el;
            const svc = this.env.services.jaguen_cols;
            if (!table || !svc || table.classList.contains("o_resizing")) {
                return;
            }
            let saved;
            try {
                saved = JSON.parse(svc.get(widthKey()) || "null");
            } catch (e) {
                saved = null;
            }
            const heads = [...table.querySelectorAll("thead th")];
            let changed = false;
            // Columnas de botones/iconos (grafica de inventario, historial de precios...): no tienen nombre ni se pueden
            // mover, asi que no se guardan; se ajustan al ancho de su icono para que no sean espacio muerto.
            for (const th of heads) {
                if (th.dataset.name || !th.classList.contains("o_list_button")) {
                    continue;
                }
                const idx = heads.indexOf(th);
                let need = 0;
                for (const row of table.querySelectorAll("tbody tr")) {
                    const cell = row.children[idx];
                    if (cell && cell.classList.contains("o_list_button")) {
                        let total = 0;
                        for (const btn of cell.querySelectorAll("button, a, .btn")) {
                            total += btn.getBoundingClientRect().width + 4;
                        }
                        need = Math.max(need, total);
                    }
                }
                th.style.width = `${Math.ceil(Math.max(32, need + 20))}px`;
                changed = true;
            }
            const avail = table.parentNode.clientWidth;
            // Lineas de ventas, compras y facturas: el ancho no depende de lo que el usuario haya guardado.
            // Las columnas cortas (cantidad, UdM, precio, impuestos, importe...) se ajustan a lo que dicen, y el espacio
            // que sobra se reparte entre Producto y Descripcion. El bote de basura siempre queda a la vista.
            if (table.classList.contains("o_section_and_note_list_view") && avail) {
                applyLineas(table, heads, avail, saved);
                return;
            }
            if (saved && saved.w && saved.pw && avail) {
                // Las columnas con ancho guardado se reparten lo que sobra despues de las demas (botones, columnas sin
                // guardar), asi la suma es justo el ancho disponible: sin hueco a la derecha y sin barra horizontal.
                let fixed = 0;
                let savedSum = 0;
                const withSaved = [];
                for (const th of heads) {
                    const w = th.dataset.name && saved.w[th.dataset.name];
                    if (w) {
                        withSaved.push([th, w]);
                        savedSum += w;
                    } else {
                        fixed += th.getBoundingClientRect().width;
                    }
                }
                if (withSaved.length) {
                    const room = Math.max(avail - fixed, 30 * withSaved.length);
                    const scale = room / savedSum;
                    const px = withSaved.map(([, w]) => Math.max(30, Math.floor(w * scale)));
                    const leftover = Math.floor(room) - px.reduce((a, b) => a + b, 0);
                    if (leftover > 0) {
                        px[px.indexOf(Math.max(...px))] += leftover;   // lo que sobra de redondear va a la columna mas ancha
                    }
                    withSaved.forEach(([th], i) => {
                        if (Math.abs(parseFloat(th.style.width || 0) - px[i]) >= 1) {
                            th.style.width = `${px[i]}px`;
                            changed = true;
                        }
                    });
                    const total = Math.floor(Math.max(avail, fixed + px.reduce((a, b) => a + b, 0)));
                    if (table.style.tableLayout !== "fixed") {
                        table.style.tableLayout = "fixed";
                    }
                    if (table.style.width !== `${total}px`) {
                        table.style.width = `${total}px`;
                    }
                }
            }
        };
        let timer = null;
        let resizeTimer = null;
        let observer = null;
        let mutationObserver = null;
        let applying = false;
        let pausadoHasta = 0;
        let rafafaInicio = 0;
        let rafafaCuenta = 0;
        // Seguro de vida: este codigo nunca debe poder trabar la pagina. Si se llegara a disparar sin parar (mas de 400
        // veces en un segundo), se detiene 2 segundos y despues retoma, asi nunca se queda en un ciclo.
        const apply = () => {
            const ahora = performance.now();
            if (applying || ahora < pausadoHasta) {
                return;
            }
            if (ahora - rafafaInicio > 1000) {
                rafafaInicio = ahora;
                rafafaCuenta = 0;
            }
            if (++rafafaCuenta > 400) {
                pausadoHasta = ahora + 2000;
                rafafaCuenta = 0;
                console.warn("jaguen_website: ajuste de columnas en pausa (se disparaba sin parar)");
                return;
            }
            applying = true;
            try {
                applyReal();
            } catch (e) {
                console.warn("jaguen_website: ajuste de columnas", e);
            } finally {
                applying = false;
                if (mutationObserver) {
                    mutationObserver.takeRecords();   // lo que escribimos nosotros no nos vuelve a llamar
                }
            }
        };
        // Odoo recalcula los anchos cuando cambia el ancho del area de la lista (ventana, barra lateral...);
        // se vuelve a aplicar de inmediato y otra vez cuando termina su recalculo.
        let anchoVisto = 0;
        const onResize = () => {
            const el = this.tableRef && this.tableRef.el && this.tableRef.el.parentNode;
            const ancho = el ? el.clientWidth : 0;
            if (ancho === anchoVisto) {
                return;   // cambio de alto, no de ancho: no hay nada que reacomodar
            }
            anchoVisto = ancho;
            apply();
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(apply, 250);
        };
        // Odoo vuelve a poner sus propios anchos de columna: se corrige en el mismo instante, antes de que se pinte.
        // Solo se atienden los cambios en los encabezados o en la tabla (no en celdas ni campos).
        let queued = false;
        const onMutated = (records) => {
            const table = this.tableRef && this.tableRef.el;
            if (!table || applying || queued) {
                return;
            }
            if (!records.some((r) => r.target === table || r.target.tagName === "TH")) {
                return;
            }
            queued = true;
            Promise.resolve().then(() => {
                queued = false;
                apply();
            });
        };
        const onPointerDown = (ev) => {
            const table = this.tableRef && this.tableRef.el;
            if (!table || !ev.target.closest || !ev.target.closest(".o_resize") || !table.contains(ev.target)) {
                return;
            }
            const onUp = () => {
                window.removeEventListener("pointerup", onUp, true);
                setTimeout(() => {
                    const svc = this.env.services.jaguen_cols;
                    if (!svc || !this.tableRef.el) {
                        return;
                    }
                    const w = {};
                    for (const th of this.tableRef.el.querySelectorAll("thead th")) {
                        if (th.dataset.name) {
                            w[th.dataset.name] = Math.round(th.getBoundingClientRect().width);
                        }
                    }
                    svc.set(widthKey(), JSON.stringify({ w, pw: this.tableRef.el.parentNode.clientWidth }));
                    apply();   // se reacomoda de inmediato con el ancho nuevo (en las lineas, con la nueva proporcion)
                }, 80);
            };
            window.addEventListener("pointerup", onUp, true);
        };
        onMounted(() => {
            anchoVisto = this.tableRef.el.parentNode ? this.tableRef.el.parentNode.clientWidth : 0;
            apply();
            clearTimeout(timer);
            timer = setTimeout(apply, 400);
            this.tableRef.el.addEventListener("pointerdown", onPointerDown, true);
            if (window.ResizeObserver && this.tableRef.el.parentNode) {
                observer = new ResizeObserver(onResize);
                observer.observe(this.tableRef.el.parentNode);
            }
            // Odoo vuelve a poner sus propios anchos al cambiar la ventana: se corrige en el mismo instante.
            if (window.MutationObserver) {
                mutationObserver = new MutationObserver(onMutated);
                mutationObserver.observe(this.tableRef.el, { attributes: true, attributeFilter: ["style"], subtree: true });
            }
        });
        onPatched(apply);
        onWillUnmount(() => {
            clearTimeout(timer);
            clearTimeout(resizeTimer);
            if (observer) {
                observer.disconnect();
            }
            if (mutationObserver) {
                mutationObserver.disconnect();
            }
        });
    },
});
