"""Marcas de agua incrementales (tabla watermark de la base de staging)."""


def get(cur, fuente):
    cur.execute("SELECT valor_utc FROM watermark WHERE fuente=%s", (fuente,))
    r = cur.fetchone()
    return r[0] if r else None


def advance(cur, fuente, valor):
    """Solo avanza (nunca retrocede)."""
    if valor is None:
        return
    cur.execute(
        """INSERT INTO watermark (fuente, valor_utc) VALUES (%s,%s)
           ON CONFLICT (fuente) DO UPDATE
           SET valor_utc = GREATEST(watermark.valor_utc, EXCLUDED.valor_utc),
               actualizado_utc = now()""", (fuente, valor))
