/* Selector de punto de entrega del checkout (Leaflet + tiles de OpenStreetMap).
 * Escribe la posición del pin en los campos ocultos delivery_latitude y
 * delivery_longitude. La validación definitiva la hace el servidor. */
(function () {
    'use strict';

    function numero(valor) {
        var n = parseFloat(valor);
        return isFinite(n) ? n : null;
    }

    function iniciar() {
        var contenedor = document.getElementById('logistica_map_picker');
        if (!contenedor || contenedor.dataset.iniciado) {
            return;
        }
        var estado = document.getElementById('logistica_map_estado');
        var campoLat = document.getElementById('delivery_latitude');
        var campoLon = document.getElementById('delivery_longitude');
        if (typeof window.L === 'undefined') {
            if (estado) {
                estado.textContent = 'No se pudo cargar el mapa. Revise su conexión y recargue la página.';
            }
            return;
        }
        contenedor.dataset.iniciado = '1';
        var L = window.L;

        var cobertura = null;
        if (contenedor.dataset.cobertura) {
            var c = contenedor.dataset.cobertura.split(',').map(numero);
            if (c.length === 4 && c.every(function (v) { return v !== null; })) {
                cobertura = L.latLngBounds([c[0], c[2]], [c[1], c[3]]);
            }
        }
        var centro = [numero(contenedor.dataset.centroLat) || -1.2417,
                      numero(contenedor.dataset.centroLon) || -78.6197];
        var lat = numero(campoLat.value);
        var lon = numero(campoLon.value);
        var tienePin = lat !== null && lon !== null && !(lat === 0 && lon === 0);

        var mapa = L.map(contenedor).setView(tienePin ? [lat, lon] : centro, 14);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '&copy; colaboradores de OpenStreetMap',
        }).addTo(mapa);
        if (cobertura) {
            L.rectangle(cobertura, {color: '#2b7a78', weight: 1, fill: false, dashArray: '4'}).addTo(mapa);
        }

        var pin = null;

        function fijar(latlng) {
            campoLat.value = latlng.lat.toFixed(7);
            campoLon.value = latlng.lng.toFixed(7);
            if (estado) {
                var fuera = cobertura && !cobertura.contains(latlng);
                estado.textContent = fuera
                    ? 'El punto está fuera de la zona de cobertura.'
                    : 'Punto de entrega seleccionado.';
                estado.className = 'form-text ' + (fuera ? 'text-danger' : 'text-success');
            }
        }

        function colocar(latlng) {
            if (!pin) {
                pin = L.marker(latlng, {draggable: true}).addTo(mapa);
                pin.on('dragend', function () { fijar(pin.getLatLng()); });
            } else {
                pin.setLatLng(latlng);
            }
            fijar(pin.getLatLng());
        }

        if (tienePin) {
            colocar(L.latLng(lat, lon));
        } else if (estado) {
            estado.textContent = 'Aún no ha seleccionado el punto de entrega.';
        }
        mapa.on('click', function (ev) { colocar(ev.latlng); });
        // El contenedor puede cambiar de tamaño al cargar el formulario.
        setTimeout(function () { mapa.invalidateSize(); }, 300);
    }

    if (document.readyState === 'complete') {
        iniciar();
    } else {
        window.addEventListener('load', iniciar);
    }
})();
