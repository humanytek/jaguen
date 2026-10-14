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
        const apply = () => {
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
            if (saved && saved.w && saved.pw && table.parentNode.clientWidth) {
                const scale = table.parentNode.clientWidth / saved.pw;
                for (const th of heads) {
                    const w = th.dataset.name && saved.w[th.dataset.name];
                    if (w) {
                        th.style.width = `${Math.max(30, Math.floor(w * scale))}px`;
                        changed = true;
                    }
                }
                table.style.tableLayout = "fixed";
                // Nunca mas angosta que el area disponible: si no, queda un hueco a la derecha y la lista se ve corrida.
                const total = heads.reduce(
                    (sum, th) => sum + parseFloat(th.style.width || th.getBoundingClientRect().width),
                    0
                );
                table.style.width = `${Math.floor(Math.max(total, table.parentNode.clientWidth))}px`;
            }
        };
        let timer = null;
        let resizeTimer = null;
        let observer = null;
        // Odoo recalcula los anchos cuando cambia el tamano del area de la lista (ventana, barra lateral...);
        // se vuelve a aplicar despues de que termine.
        const onResize = () => {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(apply, 150);
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
                }, 80);
            };
            window.addEventListener("pointerup", onUp, true);
        };
        onMounted(() => {
            apply();
            clearTimeout(timer);
            timer = setTimeout(apply, 400);
            this.tableRef.el.addEventListener("pointerdown", onPointerDown, true);
            if (window.ResizeObserver && this.tableRef.el.parentNode) {
                observer = new ResizeObserver(onResize);
                observer.observe(this.tableRef.el.parentNode);
            }
        });
        onPatched(apply);
        onWillUnmount(() => {
            clearTimeout(timer);
            clearTimeout(resizeTimer);
            if (observer) {
                observer.disconnect();
            }
        });
    },
});
