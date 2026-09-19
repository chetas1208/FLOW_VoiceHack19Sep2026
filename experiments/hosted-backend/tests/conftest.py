import pytest
from fastapi.testclient import TestClient

from cloud_helpers import Actor, make_settings
from services.flowcloud.app import create_app


def _reset_external_state():
    import os
    if os.getenv("FLOW_TEST_DATABASE_URL"):
        from sqlalchemy import text
        from services.flowcloud import db
        engine = db.make_engine(os.environ["FLOW_TEST_DATABASE_URL"])
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE")); conn.execute(text("CREATE SCHEMA public"))
        engine.dispose()
    if os.getenv("FLOW_TEST_REDIS_URL"):
        import redis
        redis.Redis.from_url(os.environ["FLOW_TEST_REDIS_URL"]).flushall()


@pytest.fixture()
def settings(tmp_path):
    _reset_external_state()
    return make_settings(tmp_path)


@pytest.fixture()
def app(settings):
    return create_app(settings)


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def alice(client):
    return Actor(client, "alice@example.com")


@pytest.fixture()
def bob(client):
    return Actor(client, "bob@example.com")
