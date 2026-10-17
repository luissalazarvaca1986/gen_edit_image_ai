import os

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

pool = AsyncConnectionPool(os.environ["DATABASE_URL"], open=False, kwargs={"row_factory": dict_row})

SCHEMA = """
CREATE TABLE IF NOT EXISTS generations (
    id              SERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    status          TEXT NOT NULL DEFAULT 'queued',   -- queued | running | done | error
    prompt          TEXT NOT NULL,
    negative_prompt TEXT NOT NULL DEFAULT '',
    model           TEXT NOT NULL,
    width           INT NOT NULL,
    height          INT NOT NULL,
    steps           INT NOT NULL,
    cfg_scale       REAL NOT NULL,
    seed            BIGINT NOT NULL,
    sampler         TEXT NOT NULL,
    strength        REAL,                              -- solo si hay referencia
    reference_path  TEXT,                              -- ruta en el volumen: /images/referencia/... o /images/generados/...
    parent_id       INT REFERENCES generations(id) ON DELETE SET NULL,  -- si la referencia fue una generación previa
    output_path     TEXT,                              -- /images/generados/...
    error           TEXT,
    duration_ms     INT
);
CREATE INDEX IF NOT EXISTS generations_created_at_idx ON generations (created_at DESC);
"""


async def init():
    await pool.open()
    async with pool.connection() as conn:
        await conn.execute(SCHEMA)
        # Lo que quedó a medias por un reinicio del contenedor ya no se va a procesar
        await conn.execute(
            "UPDATE generations SET status = 'error', error = 'Interrumpido por reinicio del servidor' "
            "WHERE status IN ('queued', 'running')"
        )


async def fetch_one(sql, params=()):
    async with pool.connection() as conn:
        cur = await conn.execute(sql, params)
        return await cur.fetchone()


async def fetch_all(sql, params=()):
    async with pool.connection() as conn:
        cur = await conn.execute(sql, params)
        return await cur.fetchall()


async def execute(sql, params=()):
    async with pool.connection() as conn:
        await conn.execute(sql, params)
