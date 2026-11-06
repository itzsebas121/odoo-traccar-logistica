"""CONNECT por base: dwh_ro no abre sesion en staging; cada rol de servicio conecta a su propia base."""
import psycopg2
import pytest

from conftest import q1


def test_dwh_ro_no_conecta_a_staging(dbs_roles):
    """psycopg2 reporta el rechazo de CONNECT como OperationalError (no como InsufficientPrivilege)."""
    e = dbs_roles
    with pytest.raises(psycopg2.OperationalError, match="permission denied for database"):
        e.connect(e.stg_db, e.ro_role)


def test_dwh_ro_conecta_a_dwh(dbs_roles):
    e = dbs_roles
    conn = e.connect(e.dwh_db, e.ro_role)
    try:
        assert q1(conn, "select 1") == 1
    finally:
        conn.close()


def test_roles_de_servicio_conectan_a_su_base(dbs_roles):
    e = dbs_roles
    for db, rol in ((e.stg_db, e.stg_user), (e.dwh_db, e.dwh_user)):
        conn = e.connect(db, rol)
        try:
            assert q1(conn, "select 1") == 1
        finally:
            conn.close()
