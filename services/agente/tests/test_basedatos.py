import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import basedatos, main

from .conftest import OdooFalso

CSRF = {'X-Agente': '1'}


@pytest.fixture
def config(tmp_path):
    respaldos = tmp_path / 'respaldos'
    respaldos.mkdir()
    return basedatos.ConfigBD(host='db', puerto='5432', usuario='odoo', clave='x', base_odoo='logistica_dev',
                              base_traccar='traccar', usuario_traccar='traccar',
                              dir_datos_odoo=tmp_path / 'odoo', dir_respaldos=respaldos)


def test_ruta_respaldo_no_sale_del_directorio(config):
    (config.dir_respaldos / 'odoo_a.zip').write_bytes(b'x')
    assert basedatos.ruta_respaldo(config, 'odoo_a.zip').name == 'odoo_a.zip'
    for malo in ('../secreto.zip', 'odoo_../../x.zip', 'otro_a.zip', 'odoo_a.sh', 'odoo_b.zip'):
        with pytest.raises(basedatos.ErrorBD):
            basedatos.ruta_respaldo(config, malo)


def test_extensiones_por_base():
    assert basedatos.nombre_para_subida('odoo', 'copia.ZIP').endswith('.zip')
    assert basedatos.nombre_para_subida('odoo', 'copia.dump').startswith('odoo_subido_')
    with pytest.raises(basedatos.ErrorBD):
        basedatos.nombre_para_subida('traccar', 'copia.zip')
    with pytest.raises(basedatos.ErrorBD):
        basedatos.nombre_para_subida('odoo', 'copia.sql')


def test_tipo_archivo(tmp_path):
    dump = tmp_path / 'a.dump'
    dump.write_bytes(b'PGDMP\x01\x0e')
    assert basedatos.tipo_archivo(dump) == 'pgdump'
    bueno = tmp_path / 'b.zip'
    with zipfile.ZipFile(bueno, 'w') as z:
        z.writestr('dump.sql', 'SELECT 1;')
    assert basedatos.tipo_archivo(bueno) == 'zip_odoo'
    malo = tmp_path / 'c.zip'
    with zipfile.ZipFile(malo, 'w') as z:
        z.writestr('otro.txt', 'x')
    with pytest.raises(basedatos.ErrorBD):
        basedatos.tipo_archivo(malo)
    texto = tmp_path / 'd.dump'
    texto.write_text('hola')
    with pytest.raises(basedatos.ErrorBD):
        basedatos.tipo_archivo(texto)


def test_filestore_rechaza_zip_slip(tmp_path):
    archivo = tmp_path / 'malo.zip'
    with zipfile.ZipFile(archivo, 'w') as z:
        z.writestr('dump.sql', 'x')
        z.writestr('filestore/../../fuera.txt', 'x')
    with zipfile.ZipFile(archivo) as z, pytest.raises(basedatos.ErrorBD):
        basedatos._extraer_filestore(z, tmp_path / 'destino')
    assert not (tmp_path / 'fuera.txt').exists()


def test_listar_ignora_archivos_ajenos(config):
    for nombre in ('odoo_logistica_dev_20260101_000000.zip', 'traccar_t_1_antes-de-restaurar.dump', 'notas.txt',
                   'odoo_x.parcial'):
        (config.dir_respaldos / nombre).write_bytes(b'x')
    nombres = {r['nombre']: r for r in basedatos.listar(config)}
    assert set(nombres) == {'odoo_logistica_dev_20260101_000000.zip', 'traccar_t_1_antes-de-restaurar.dump'}
    assert nombres['traccar_t_1_antes-de-restaurar.dump']['automatico'] is True


# ------------------------------------------------------------------ API
@pytest.fixture
def cliente(monkeypatch, config):
    monkeypatch.setattr(main, 'odoo', OdooFalso())
    monkeypatch.setattr(main, 'config_bd', config)
    monkeypatch.setattr(main, 'limite_login', main.Limitador(100, 60))
    monkeypatch.setattr(main, 'limite_maestra', main.Limitador(100, 60))
    monkeypatch.setenv('ODOO_MASTER_PASSWORD', 'maestra')
    c = TestClient(main.app)
    assert c.post('/api/login', json={'login': 'admin@x', 'clave': 'buena'}, headers=CSRF).status_code == 200
    return c


def test_respaldo_exige_clave_maestra(cliente, monkeypatch):
    llamado = []
    monkeypatch.setattr(basedatos, 'respaldar', lambda *a: llamado.append(a))
    r = cliente.post('/api/bd/respaldos', json={'base': 'odoo', 'clave_maestra': 'mala'}, headers=CSRF)
    assert r.status_code == 403 and not llamado
    assert cliente.post('/api/bd/respaldos', json={'base': 'odoo', 'clave_maestra': 'maestra'}).status_code == 403  # sin CSRF


def test_restaurar_exige_confirmacion_y_valida_subida(cliente, monkeypatch, config):
    restaurados = []
    monkeypatch.setattr(basedatos, 'restaurar', lambda cfg, base, ruta, quien: restaurados.append((base, ruta.name))
                        or {'base': base, 'archivo': ruta.name})
    datos = {'base': 'traccar', 'clave_maestra': 'maestra', 'confirmacion': 'no'}
    archivo = {'archivo': ('copia.dump', io.BytesIO(b'PGDMP...'), 'application/octet-stream')}
    assert cliente.post('/api/bd/restaurar', data=datos, files=archivo, headers=CSRF).status_code == 400
    datos['confirmacion'] = 'RESTAURAR'
    archivo = {'archivo': ('copia.zip', io.BytesIO(b'x'), 'application/zip')}
    assert cliente.post('/api/bd/restaurar', data=datos, files=archivo, headers=CSRF).status_code == 400
    archivo = {'archivo': ('copia.dump', io.BytesIO(b'PGDMP...'), 'application/octet-stream')}
    r = cliente.post('/api/bd/restaurar', data=datos, files=archivo, headers=CSRF)
    assert r.status_code == 200, r.text
    assert restaurados[0][0] == 'traccar' and restaurados[0][1].startswith('traccar_subido_')
    assert (config.dir_respaldos / restaurados[0][1]).read_bytes() == b'PGDMP...'


def test_descarga_y_borrado(cliente, config):
    (config.dir_respaldos / 'odoo_copia.zip').write_bytes(b'contenido')
    r = cliente.get('/api/bd/respaldos/odoo_copia.zip')
    assert r.status_code == 200 and r.content == b'contenido'
    assert 'attachment' in r.headers['content-disposition']
    assert cliente.get('/api/bd/respaldos/..%2F..%2Fetc%2Fpasswd').status_code == 404
    r = cliente.post('/api/bd/respaldos/odoo_copia.zip/borrar', json={'clave_maestra': 'maestra'}, headers=CSRF)
    assert r.status_code == 200 and not Path(config.dir_respaldos / 'odoo_copia.zip').exists()


def test_sin_sesion_no_hay_acceso(config, monkeypatch):
    monkeypatch.setattr(main, 'config_bd', config)
    c = TestClient(main.app)
    assert c.get('/api/bd').status_code == 401
    assert c.get('/api/bd/respaldos/odoo_copia.zip').status_code == 401
