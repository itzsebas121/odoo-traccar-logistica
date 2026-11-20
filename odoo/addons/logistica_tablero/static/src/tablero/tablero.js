/** @odoo-module **/
/**
 * Tablero de indicadores (acción de cliente `logistica_tablero.tablero`).
 * Muestra a pantalla completa /logistica/tablero/app: el MISMO tablero (React + shadcn) del asistente, compilado en
 * static/app, que pide sus datos a /logistica/tablero/api/<sección> con la sesión de Odoo. Va en un iframe del mismo
 * origen para que sus estilos (Tailwind) y los de Odoo no se mezclen.
 */
import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";

export class TableroIndicadores extends Component {}

TableroIndicadores.template = "logistica_tablero.TableroIndicadores";

registry.category("actions").add("logistica_tablero.tablero", TableroIndicadores);
