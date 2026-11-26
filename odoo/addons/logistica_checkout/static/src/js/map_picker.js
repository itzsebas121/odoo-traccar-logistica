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
        // En móvil (<768px) el CSS del website de Odoo aplica
        // `img:not(.o_animate) { transform: none !important; }`, lo que anula el
        // translate3d con que Leaflet coloca teselas y pines (todas quedan
        // apiladas en la esquina). Sin any3d, Leaflet posiciona con left/top.
        L.Browser.any3d = false;

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
        var teselas = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '&copy; colaboradores de OpenStreetMap',
        }).addTo(mapa);
        teselas.on('tileerror', function (ev) {
            if (window.console) {
                console.warn('[mapa entrega] no se pudo cargar la tesela', ev.coords);
            }
        });
        // Fase A: la cobertura real es un radio desde la bodega (si está configurado).
        var radioKm = numero(contenedor.dataset.radioKm);
        var sede = (contenedor.dataset.sede || '').split(',').map(numero);
        var circulo = null;
        if (radioKm && sede.length === 2 && sede[0] !== null && sede[1] !== null) {
            circulo = L.circle(sede, {radius: radioKm * 1000, color: '#2b7a78', weight: 1, fillOpacity: 0.04,
                                      dashArray: '4'}).addTo(mapa);
        } else if (cobertura) {
            L.rectangle(cobertura, {color: '#2b7a78', weight: 1, fill: false, dashArray: '4'}).addTo(mapa);
        }

        var pin = null;
        var botonQuitar = document.getElementById('logistica_map_quitar');
        var SIN_PUNTO = 'Aún no ha seleccionado el punto de entrega.';

        function fijar(latlng) {
            campoLat.value = latlng.lat.toFixed(7);
            campoLon.value = latlng.lng.toFixed(7);
            if (estado) {
                var fuera = (cobertura && !cobertura.contains(latlng)) ||
                    (circulo && mapa.distance(circulo.getLatLng(), latlng) > circulo.getRadius());
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
            if (botonQuitar) {
                botonQuitar.classList.remove('d-none');
            }
        }

        // Quitar el punto: vacía los campos ocultos (el servidor pedirá marcar uno antes de continuar).
        function quitar() {
            if (pin) {
                mapa.removeLayer(pin);
                pin = null;
            }
            campoLat.value = '';
            campoLon.value = '';
            if (estado) {
                estado.textContent = SIN_PUNTO;
                estado.className = 'form-text text-muted';
            }
            if (botonQuitar) {
                botonQuitar.classList.add('d-none');
            }
        }
        if (botonQuitar) {
            botonQuitar.addEventListener('click', quitar);
        }

        if (tienePin) {
            colocar(L.latLng(lat, lon));
        } else if (estado) {
            estado.textContent = SIN_PUNTO;
        }
        mapa.on('click', function (ev) { colocar(ev.latlng); });
        // El contenedor cambia de tamaño al cargar el formulario, al rotar el
        // móvil o al abrir/cerrar el teclado: Leaflet debe recalcular su tamaño
        // o solo pinta las teselas del tamaño inicial (resto en gris).
        var pendiente = null;
        function reajustar() {
            if (pendiente) {
                cancelAnimationFrame(pendiente);
            }
            pendiente = requestAnimationFrame(function () {
                pendiente = null;
                mapa.invalidateSize({pan: false});
            });
        }
        if (typeof window.ResizeObserver !== 'undefined') {
            new ResizeObserver(reajustar).observe(contenedor);
        }
        window.addEventListener('resize', reajustar);
        window.addEventListener('orientationchange', reajustar);
        [100, 300, 1000].forEach(function (ms) { setTimeout(reajustar, ms); });
    }

    if (document.readyState === 'complete') {
        iniciar();
    } else {
        window.addEventListener('load', iniciar);
    }
})();
