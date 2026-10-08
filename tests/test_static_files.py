from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from static_files import NoCacheStaticFiles


def make_client(directory) -> TestClient:
    app = Starlette(routes=[Mount("/static", app=NoCacheStaticFiles(directory=directory))])
    return TestClient(app)


def test_static_asset_is_served_with_no_cache(tmp_path):
    (tmp_path / "app.js").write_text("console.log('hi');")
    client = make_client(tmp_path)

    response = client.get("/static/app.js")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert "etag" in response.headers


def test_not_modified_response_keeps_no_cache(tmp_path):
    (tmp_path / "app.js").write_text("console.log('hi');")
    client = make_client(tmp_path)
    etag = client.get("/static/app.js").headers["etag"]

    response = client.get("/static/app.js", headers={"If-None-Match": etag})

    assert response.status_code == 304
    assert response.headers["cache-control"] == "no-cache"
