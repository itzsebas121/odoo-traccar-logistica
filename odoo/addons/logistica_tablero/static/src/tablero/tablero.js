/** @odoo-module **/
/**
 * Tablero de indicadores (acción de cliente `logistica_tablero.tablero`).
 * Pide cada sección a /logistica/tablero/api/<sección> (DWH, solo lectura) y la dibuja con Chart.js (el de Odoo)
 * y Leaflet (el de logistica_base). Mismas secciones y filtros que el tablero del asistente.
 */
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadCSS, loadJS } from "@web/core/assets";
import { Component, onMounted, onPatched, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";

const PESTANAS = [
    { id: "resumen", nombre: "Resumen" },
    { id: "demanda", nombre: "Demanda" },
    { id: "pronostico", nombre: "Pronóstico" },
    { id: "operacion", nombre: "Operación" },
];
const PERIODOS = [
    { id: "ultimas", nombre: "Últimos 30 días con ventas" },
    { id: "7", nombre: "Últimos 7 días" },
    { id: "30", nombre: "Últimos 30 días" },
    { id: "90", nombre: "Últimos 90 días" },
    { id: "anio", nombre: "Este año" },
    { id: "rango", nombre: "Elegir fechas" },
];
const COLORES = ["#1B263B", "#E06D2B", "#1D8A68", "#6B7FA3", "#C9A227", "#9C4F96", "#3E8EBF", "#B5523B"];
const COLOR_RESULTADO = { entregado: "#1D8A68", no_entregado: "#B5523B", pendiente: "#C9A227" };
const TESELAS = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATRIBUCION = "&copy; OpenStreetMap";

const num = new Intl.NumberFormat("es-EC", { maximumFractionDigits: 0 });
const dec = new Intl.NumberFormat("es-EC", { maximumFractionDigits: 1 });
const dinero = new Intl.NumberFormat("es-EC", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const dineroExacto = new Intl.NumberFormat("es-EC", { style: "currency", currency: "USD" });

function isoLocal(d) {
    const z = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
}

function diaCorto(iso) {
    const [, m, d] = String(iso).slice(0, 10).split("-");
    return `${d}/${m}`;
}

export class TableroIndicadores extends Component {
    setup() {
        this.rpc = useService("rpc");
        this.pestanas = PESTANAS;
        this.periodos = PERIODOS;
        this.fmt = {
            num: (v) => (v === null || v === undefined ? "—" : num.format(v)),
            dec: (v) => (v === null || v === undefined ? "—" : dec.format(v)),
            dinero: (v) => (v === null || v === undefined ? "—" : dinero.format(v)),
            dineroExacto: (v) => (v === null || v === undefined ? "—" : dineroExacto.format(v)),
            pct: (v) => (v === null || v === undefined ? "—" : `${dec.format(v)} %`),
            variacion: (v) => (v === null || v === undefined ? "" : `${v > 0 ? "▲" : v < 0 ? "▼" : "="} ${dec.format(Math.abs(v))} % vs. 7 días previos`),
            dia: diaCorto,
        };
        this.state = useState({
            pestana: "resumen",
            filtros: { periodo: "ultimas", desde: "", hasta: "", zona: "", categoria: "", procedencia: "", conductor: "" },
            opciones: { zonas: [], categorias: [], conductores: [] },
            datos: null,
            detalle: null,
            producto: "",
            cargando: false,
            error: null,
        });
        this.lienzos = {
            ventas: useRef("graficoVentas"),
            pedidos: useRef("graficoPedidos"),
            negocio: useRef("graficoNegocio"),
            categorias: useRef("graficoCategorias"),
            zonas: useRef("graficoZonas"),
            detalle: useRef("graficoDetalle"),
            porDia: useRef("graficoPorDia"),
            conductores: useRef("graficoConductores"),
            mapa: useRef("mapa"),
        };
        this.graficos = [];
        this.mapa = null;
        this.dibujado = null;

        onWillStart(async () => {
            await Promise.all([
                loadJS("/web/static/lib/Chart/Chart.js"),
                loadJS("/logistica_base/static/lib/leaflet/leaflet.js"),
                loadCSS("/logistica_base/static/lib/leaflet/leaflet.css"),
            ]);
            const opciones = await this.pedir("opciones");
            if (opciones && !opciones.error) {
                this.state.opciones = opciones;
            }
            await this.cargar();
        });
        onMounted(() => this.dibujar());
        onPatched(() => this.dibujar());
        onWillUnmount(() => this.limpiar());
    }

    // ------------------------------------------------------------------ datos
    async pedir(seccion, extra = {}) {
        try {
            return await this.rpc(`/logistica/tablero/api/${seccion}`, { ...this.parametros(), ...extra });
        } catch (e) {
            return { error: (e && e.message) || "No se pudo contactar con el servidor." };
        }
    }

    parametros() {
        const f = this.state.filtros;
        const hoy = new Date();
        let desde = null;
        let hasta = null;
        if (f.periodo === "rango") {
            desde = f.desde || null;
            hasta = f.hasta || null;
        } else if (f.periodo === "anio") {
            desde = `${hoy.getFullYear()}-01-01`;
            hasta = isoLocal(hoy);
        } else if (f.periodo !== "ultimas") {
            const d = new Date(hoy);
            d.setDate(d.getDate() - (Number(f.periodo) - 1));
            desde = isoLocal(d);
            hasta = isoLocal(hoy);
        }
        return {
            desde, hasta,
            zona: f.zona || null,
            categoria: f.categoria || null,
            procedencia: f.procedencia || null,
            conductor: f.conductor || null,
        };
    }

    async cargar() {
        this.state.cargando = true;
        this.state.error = null;
        const seccion = this.state.pestana;
        const datos = await this.pedir(seccion);
        let detalle = null;
        if (seccion === "pronostico" && datos && !datos.error && datos.celdas.length) {
            detalle = await this.pedir("pronostico_detalle", { producto_sk: this.state.producto || null });
        }
        if (seccion !== this.state.pestana) {
            return; // el usuario cambió de pestaña mientras se cargaba
        }
        this.dibujado = null;
        this.state.datos = datos && !datos.error ? datos : null;
        this.state.detalle = detalle && !detalle.error ? detalle : null;
        this.state.error = datos && datos.error ? datos.error : null;
        this.state.cargando = false;
    }

    async cambiarPestana(id) {
        if (id === this.state.pestana) {
            return;
        }
        this.limpiar();
        this.state.pestana = id;
        this.state.datos = null;
        await this.cargar();
    }

    async cambiarFiltro(campo, ev) {
        this.state.filtros[campo] = ev.target.value;
        if (campo === "periodo" && ev.target.value === "rango") {
            return; // espera a que elija las fechas
        }
        await this.cargar();
    }

    async cambiarProducto(ev) {
        this.state.producto = ev.target.value;
        const detalle = await this.pedir("pronostico_detalle", { producto_sk: this.state.producto || null });
        this.dibujado = null;
        this.state.detalle = detalle && !detalle.error ? detalle : null;
    }

    // ------------------------------------------------------------------ vistas derivadas
    get diasResumen() {
        const porDia = new Map();
        for (const r of (this.state.datos && this.state.datos.serie) || []) {
            const d = porDia.get(r.fecha) || { fecha: r.fecha, REAL: 0, SIMULADO: 0, pedidos: 0 };
            d[r.procedencia] = (d[r.procedencia] || 0) + (r.importe || 0);
            d.pedidos += r.pedidos || 0;
            porDia.set(r.fecha, d);
        }
        return [...porDia.values()].sort((a, b) => a.fecha.localeCompare(b.fecha));
    }

    get pronosticoNegocio() {
        const filas = (this.state.datos && this.state.datos.pronostico_total) || [];
        const total = filas.filter((f) => f.tipo === "pronostico").reduce((s, f) => s + f.pronostico, 0);
        const vendido = filas.filter((f) => f.tipo === "backtest").reduce((s, f) => s + (f.real || 0), 0);
        return { hay: filas.length > 0, total, vendido, cambio: vendido > 0 ? (100 * (total - vendido)) / vendido : null };
    }

    get productosPronostico() {
        const vistos = new Map();
        for (const c of (this.state.datos && this.state.datos.celdas) || []) {
            vistos.set(c.producto_sk, c.producto);
        }
        return [...vistos.entries()].map(([sk, nombre]) => ({ sk, nombre })).sort((a, b) => a.nombre.localeCompare(b.nombre));
    }

    get celdasOrdenadas() {
        return [...((this.state.datos && this.state.datos.celdas) || [])].sort((a, b) => b.unidades - a.unidades).slice(0, 60);
    }

    nombreZona(codigo) {
        const z = this.state.opciones.zonas.find((x) => x.codigo === codigo);
        return z ? z.nombre : codigo;
    }

    // ------------------------------------------------------------------ dibujo
    limpiar() {
        for (const g of this.graficos) {
            g.destroy();
        }
        this.graficos = [];
        if (this.mapa) {
            this.mapa.remove();
            this.mapa = null;
        }
        this.dibujado = null;
    }

    dibujar() {
        const clave = this.state.datos ? `${this.state.pestana}` : null;
        if (!clave || this.dibujado === this.state.datos) {
            return;
        }
        this.limpiar();
        this.dibujado = this.state.datos;
        const d = this.state.datos;
        const p = this.state.pestana;
        if (p === "resumen") {
            const dias = this.diasResumen;
            const series = ["REAL", "SIMULADO"].filter((s) => dias.some((x) => x[s] > 0));
            this.barras(this.lienzos.ventas, dias.map((x) => diaCorto(x.fecha)),
                series.map((s, i) => ({ label: s === "REAL" ? "Reales" : "Simulados", data: dias.map((x) => x[s]), backgroundColor: COLORES[i] })),
                { apiladas: true, dinero: true });
            this.lineas(this.lienzos.pedidos, dias.map((x) => diaCorto(x.fecha)),
                [{ label: "Pedidos", data: dias.map((x) => x.pedidos), borderColor: COLORES[0] }]);
            const filas = d.pronostico_total || [];
            this.lineas(this.lienzos.negocio, filas.map((f) => diaCorto(f.fecha)), [
                { label: "Vendido", data: filas.map((f) => (f.tipo === "backtest" ? f.real : null)), borderColor: COLORES[0] },
                { label: "Pronóstico", data: filas.map((f) => f.pronostico), borderColor: COLORES[1], borderDash: [6, 4] },
            ]);
        } else if (p === "demanda") {
            const cat = (d.categorias || []).slice(0, 12);
            this.barras(this.lienzos.categorias, cat.map((c) => c.categoria),
                [{ label: "Ventas", data: cat.map((c) => c.importe), backgroundColor: COLORES[0] }], { horizontal: true, dinero: true });
            const zonas = d.zonas || [];
            this.barras(this.lienzos.zonas, zonas.map((z) => z.nombre),
                [{ label: "Ventas", data: zonas.map((z) => z.importe), backgroundColor: COLORES[1] }], { horizontal: true, dinero: true });
            this.mapaPuntos((d.puntos || []).map((x) => ({
                lat: x.latitud, lon: x.longitud, valor: x.importe,
                texto: `${this.fmt.dineroExacto(x.importe)} · ${this.fmt.num(x.pedidos)} pedidos · ${this.fmt.num(x.unidades)} u.`,
            })));
        } else if (p === "pronostico") {
            const serie = (this.state.detalle && this.state.detalle.serie) || [];
            this.lineas(this.lienzos.detalle, serie.map((r) => diaCorto(r.fecha)), [
                { label: "Vendido", data: serie.map((r) => r.real), borderColor: COLORES[0] },
                { label: "Pronóstico", data: serie.map((r) => r.pronostico), borderColor: COLORES[1], borderDash: [6, 4] },
                { label: "Máximo probable", data: serie.map((r) => r.p90), borderColor: "rgba(224,109,43,0.35)", borderDash: [2, 3] },
            ]);
            if ((d.unidades || []).length) {
                // Unidades de ubicación del modelo, en el centro real de sus pedidos.
                this.mapaPuntos(d.unidades.map((u) => ({
                    lat: u.latitud, lon: u.longitud, valor: u.unidades,
                    texto: `${this.nombreZona(u.zona)}: ${this.fmt.dec(u.unidades)} u. esperadas en 7 días`,
                })), COLORES[1]);
            } else {
                const porZona = new Map();
                for (const c of d.celdas || []) {
                    porZona.set(c.zona, (porZona.get(c.zona) || 0) + c.unidades);
                }
                this.mapaPuntos((d.zonas || []).filter((z) => porZona.has(z.codigo)).map((z) => ({
                    lat: z.latitud, lon: z.longitud, valor: porZona.get(z.codigo),
                    texto: `${z.nombre}: ${this.fmt.dec(porZona.get(z.codigo))} u. esperadas en 7 días`,
                })), COLORES[1]);
            }
        } else if (p === "operacion") {
            const fechas = [...new Set((d.por_dia || []).map((r) => r.fecha))].sort();
            const resultados = [...new Set((d.por_dia || []).map((r) => r.resultado))];
            this.barras(this.lienzos.porDia, fechas.map(diaCorto), resultados.map((res, i) => ({
                label: res.replace("_", " "),
                data: fechas.map((f) => ((d.por_dia || []).find((r) => r.fecha === f && r.resultado === res) || {}).entregas || 0),
                backgroundColor: COLOR_RESULTADO[res] || COLORES[i],
            })), { apiladas: true });
            const cond = d.conductores || [];
            this.barras(this.lienzos.conductores, cond.map((c) => c.conductor), [
                { label: "Km planificados", data: cond.map((c) => c.km_plan), backgroundColor: COLORES[3] },
                { label: "Km reales", data: cond.map((c) => c.km_real), backgroundColor: COLORES[0] },
            ], { horizontal: true });
        }
    }

    opcionesBase(extra = {}) {
        return {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 0 },
            legend: { display: extra.leyenda !== false, position: "bottom", labels: { boxWidth: 12, fontColor: "#5C677A" } },
            tooltips: {
                mode: "index", intersect: false,
                callbacks: extra.dinero ? { label: (t, data) => `${data.datasets[t.datasetIndex].label}: ${dineroExacto.format(t[extra.horizontal ? "xLabel" : "yLabel"])}` } : {},
            },
        };
    }

    barras(ref, etiquetas, datasets, { apiladas = false, horizontal = false, dinero: esDinero = false } = {}) {
        if (!ref.el || !window.Chart) {
            return;
        }
        const eje = { stacked: apiladas, gridLines: { color: "rgba(20,29,43,0.06)" }, ticks: { beginAtZero: true, fontColor: "#5C677A" } };
        if (esDinero) {
            eje.ticks.callback = (v) => dinero.format(v);
        }
        const otro = { stacked: apiladas, gridLines: { display: false }, ticks: { fontColor: "#5C677A", autoSkip: true, maxRotation: 0 } };
        this.graficos.push(new window.Chart(ref.el, {
            type: horizontal ? "horizontalBar" : "bar",
            data: { labels: etiquetas, datasets: datasets.map((ds) => ({ maxBarThickness: 28, ...ds })) },
            options: {
                ...this.opcionesBase({ dinero: esDinero, horizontal, leyenda: datasets.length > 1 }),
                scales: horizontal ? { xAxes: [eje], yAxes: [otro] } : { xAxes: [otro], yAxes: [eje] },
            },
        }));
    }

    lineas(ref, etiquetas, datasets) {
        if (!ref.el || !window.Chart) {
            return;
        }
        this.graficos.push(new window.Chart(ref.el, {
            type: "line",
            data: {
                labels: etiquetas,
                datasets: datasets.map((ds) => ({ fill: false, pointRadius: 0, borderWidth: 2, lineTension: 0, spanGaps: false, ...ds })),
            },
            options: {
                ...this.opcionesBase({ leyenda: datasets.length > 1 }),
                scales: {
                    xAxes: [{ gridLines: { display: false }, ticks: { fontColor: "#5C677A", autoSkip: true, maxRotation: 0 } }],
                    yAxes: [{ gridLines: { color: "rgba(20,29,43,0.06)" }, ticks: { beginAtZero: true, fontColor: "#5C677A" } }],
                },
            },
        }));
    }

    mapaPuntos(puntos, color = COLORES[0]) {
        const el = this.lienzos.mapa.el;
        if (!el || !window.L) {
            return;
        }
        const validos = puntos.filter((x) => x.lat !== null && x.lon !== null && x.lat !== undefined);
        this.mapa = window.L.map(el, { scrollWheelZoom: false });
        window.L.tileLayer(TESELAS, { attribution: ATRIBUCION, maxZoom: 19 }).addTo(this.mapa);
        if (!validos.length) {
            this.mapa.setView([-1.2417, -78.6197], 13);
            return;
        }
        const maximo = Math.max(...validos.map((x) => x.valor || 0), 1);
        const capa = window.L.featureGroup();
        for (const x of validos) {
            window.L.circleMarker([x.lat, x.lon], {
                radius: 4 + 16 * Math.sqrt((x.valor || 0) / maximo),
                color, weight: 1, fillColor: color, fillOpacity: 0.45,
            }).bindTooltip(x.texto).addTo(capa);
        }
        capa.addTo(this.mapa);
        this.mapa.fitBounds(capa.getBounds().pad(0.15), { maxZoom: 16 });
        setTimeout(() => this.mapa && this.mapa.invalidateSize(), 0);
    }
}

TableroIndicadores.template = "logistica_tablero.TableroIndicadores";

registry.category("actions").add("logistica_tablero.tablero", TableroIndicadores);
