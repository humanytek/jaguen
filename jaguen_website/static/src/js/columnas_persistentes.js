/** @odoo-module **/
// Columnas opcionales de las listas: se guardan por usuario en el servidor y con una llave estable.
// Odoo las guarda solo en localStorage y su llave incluye la lista de campos de la vista, asi que se pierden al
// cambiar de navegador/equipo o cuando una actualizacion agrega o quita un campo de esa pantalla.
import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { ListRenderer } from "@web/views/list/list_renderer";
import { user } from "@web/core/user";

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
