from sqlalchemy import text


def test_conexion_a_la_base(engine):
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar_one() == 1


def test_postgres_es_version_16(engine):
    with engine.connect() as conn:
        version = conn.execute(text("SHOW server_version_num")).scalar_one()

    assert version.startswith("16")


def test_extension_vector_instalada(engine):
    with engine.connect() as conn:
        instalada = conn.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one_or_none()

    assert instalada is not None, "Falta la extensión vector: corre `make migrate`"
