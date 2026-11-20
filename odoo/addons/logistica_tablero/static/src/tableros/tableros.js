/** @odoo-module **/
/**
 * Indicadores logísticos dentro de la app «Tableros» de Odoo.
 * Agrega al panel izquierdo de Tableros (SALES, FINANCE...) un grupo LOGÍSTICA con «Indicadores logísticos»: al
 * elegirlo, el área principal muestra el tablero shadcn (/logistica/tablero/app) en vez de una hoja de cálculo.
 * Es el que se abre por defecto para quien puede verlo (gerentes de ventas o de flota: session.logistica_tablero,
 * ver models/ir_http.py). Los tableros estándar (Sales, Product, Invoicing...) siguen igual.
 */
import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";
import { SpreadsheetDashboardAction } from "@spreadsheet_dashboard/bundle/dashboard_action/dashboard_action";

const { useState } = owl;

patch(SpreadsheetDashboardAction.prototype, "logistica_tablero.IndicadoresEnTableros", {
    setup() {
        const visible = Boolean(session.logistica_tablero) && !this.env.isSmall;
        const estado = this.props.state || {};
        const params = this.props.action.params || (this.props.action.context || {}).params || {};
        // Por defecto los indicadores, salvo que se vuelva a un tablero concreto (miga de pan o URL con dashboard_id).
        const activo = visible && !estado.activeDashboardId && !params.dashboard_id;
        this.logistica = useState({ visible, activo });
        this._super(...arguments);
    },

    getInitialActiveDashboard() {
        return this.logistica.activo ? undefined : this._super(...arguments);
    },

    abrirIndicadores() {
        this.logistica.activo = true;
        this.state.activeDashboard = undefined;
    },

    openDashboard(dashboardId) {
        this.logistica.activo = false;
        return this._super(dashboardId);
    },
});
