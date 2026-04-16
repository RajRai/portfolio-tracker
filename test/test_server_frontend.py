from src import server


def test_frontend_deep_link_serves_react_index(monkeypatch, tmp_path):
    index_path = tmp_path / "index.html"
    index_path.write_text("<!doctype html><div id=\"root\"></div>", encoding="utf-8")
    monkeypatch.setattr(server, "CLIENT_DIR", tmp_path)

    response = server.app.test_client().get("/tools/market-cap-weights")

    assert response.status_code == 200
    assert b'<div id="root"></div>' in response.data


def test_frontend_static_asset_served_from_dist(monkeypatch, tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('ok');", encoding="utf-8")
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(server, "CLIENT_DIR", tmp_path)

    response = server.app.test_client().get("/assets/app.js")

    assert response.status_code == 200
    assert response.data == b"console.log('ok');"

