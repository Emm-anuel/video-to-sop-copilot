from sqlalchemy.exc import OperationalError

from sopvid.plataforma.db import get_session


def test_health_ok_con_base_real(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


def test_health_503_si_la_base_no_responde(client):
    class SesionCaida:
        def execute(self, *args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    client.app.dependency_overrides[get_session] = lambda: SesionCaida()

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "db": "error"}
