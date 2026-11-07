/* Dibuja la ruta sugerida guardada en la consulta. No consulta ningún servicio. */
(function () {
    'use strict';
    document.addEventListener('DOMContentLoaded', function () {
        var el = document.getElementById('prediccion-mapa');
        var mapa = L.map(el).setView([-1.2417, -78.6197], 13);
        L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19, attribution: '&copy; OpenStreetMap'
        }).addTo(mapa);
        var puntos = [];
        try { puntos = JSON.parse(el.getAttribute('data-geometria') || '[]'); } catch (e) { puntos = []; }
        if (puntos.length > 1) {
            var linea = L.polyline(puntos, {color: '#2563eb', weight: 4}).addTo(mapa);
            L.marker(puntos[0]).bindTooltip('Origen').addTo(mapa);
            L.marker(puntos[puntos.length - 1]).bindTooltip('Destino probable').addTo(mapa);
            mapa.fitBounds(linea.getBounds(), {padding: [30, 30]});
        }
    });
}());
