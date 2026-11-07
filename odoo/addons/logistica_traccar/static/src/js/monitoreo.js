/* Mapa de monitoreo. Los datos llegan de /logistica/monitoreo/data; Traccar nunca se consulta desde aquí. */
(function () {
    'use strict';

    var REFRESCO_MS = 10000;
    var mapa = null;
    var capas = null;
    var primeraVez = true;

    function texto(tag, contenido, estilo) {
        var el = document.createElement(tag);
        el.textContent = contenido;
        if (estilo) { el.style.cssText = estilo; }
        return el;
    }

    function formatoEdad(segundos) {
        if (segundos === null || segundos === undefined) { return 'sin datos'; }
        if (segundos < 60) { return segundos + ' s'; }
        if (segundos < 3600) { return Math.round(segundos / 60) + ' min'; }
        return (segundos / 3600).toFixed(1) + ' h';
    }

    function popupVehiculo(v) {
        var gps = v.gps;
        var caja = document.createElement('div');
        caja.appendChild(texto('strong', v.placa));
        if (v.conductor) { caja.appendChild(texto('div', 'Conductor: ' + v.conductor)); }
        if (!gps.tiene_posicion) {
            caja.appendChild(texto('div', 'Sin posición GPS todavía.'));
            return caja;
        }
        if (gps.desactualizado) {
            caja.appendChild(texto('div', 'Última ubicación conocida', 'color:#b45309;font-weight:bold'));
        }
        caja.appendChild(texto('div', 'Hace ' + formatoEdad(gps.antiguedad_s)));
        caja.appendChild(texto('div', 'Hora GPS (UTC): ' + gps.ultima_ubicacion_conocida.hora_gps));
        caja.appendChild(texto('div', 'Velocidad: ' + gps.ultima_ubicacion_conocida.velocidad_kmh + ' km/h'));
        if (v.ruta) { caja.appendChild(texto('div', 'Ruta: ' + v.ruta.nombre)); }
        return caja;
    }

    function dibujar(datos) {
        capas.clearLayers();
        var limites = [];
        var obsoletos = 0;
        datos.vehiculos.forEach(function (v) {
            var gps = v.gps;
            if (gps.tiene_posicion) {
                var u = gps.ultima_ubicacion_conocida;
                var p = [u.latitud, u.longitud];
                limites.push(p);
                if (gps.desactualizado) { obsoletos += 1; }
                L.circleMarker(p, {
                    radius: 9, weight: 2,
                    color: gps.desactualizado ? '#b45309' : '#047857',
                    fillColor: gps.desactualizado ? '#f59e0b' : '#10b981',
                    fillOpacity: 0.85
                }).bindPopup(popupVehiculo(v)).bindTooltip(v.placa).addTo(capas);
            }
            if (v.ruta) {
                var r = v.ruta;
                if (r.recorrido.length > 1) {
                    L.polyline(r.recorrido, {color: '#2563eb', weight: 3}).addTo(capas);
                }
                L.marker([r.bodega.latitud, r.bodega.longitud]).bindTooltip('Bodega').addTo(capas);
                r.paradas.forEach(function (s) {
                    var color = s.estado === 'entregado' ? '#047857' : (s.estado === 'no_entregado' ? '#b91c1c' : '#6b7280');
                    var marcador = L.circleMarker([s.latitud, s.longitud], {
                        radius: 6, color: color, fillColor: color, fillOpacity: 0.7
                    });
                    marcador.bindTooltip(s.orden + '. ' + s.referencia + (s.posible_llegada ? ' (posible llegada)' : ''));
                    marcador.addTo(capas);
                    limites.push([s.latitud, s.longitud]);
                });
            }
        });
        if (primeraVez && limites.length) {
            mapa.fitBounds(limites, {padding: [40, 40], maxZoom: 16});
            primeraVez = false;
        }
        var aviso = document.getElementById('monitoreo-aviso');
        aviso.textContent = datos.vehiculos.length + ' vehículo(s)' +
            (obsoletos ? ' · ' + obsoletos + ' con señal antigua' : '');
    }

    function cargar() {
        fetch('/logistica/monitoreo/data', {credentials: 'same-origin'})
            .then(function (r) {
                if (!r.ok) { throw new Error('HTTP ' + r.status); }
                return r.json();
            })
            .then(dibujar)
            .catch(function (e) {
                document.getElementById('monitoreo-aviso').textContent = 'No se pudo actualizar (' + e.message + ')';
            });
    }

    document.addEventListener('DOMContentLoaded', function () {
        mapa = L.map('monitoreo-mapa').setView([-1.2417, -78.6197], 13);
        L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19, attribution: '&copy; OpenStreetMap'
        }).addTo(mapa);
        capas = L.layerGroup().addTo(mapa);
        cargar();
        setInterval(cargar, REFRESCO_MS);
    });
}());
