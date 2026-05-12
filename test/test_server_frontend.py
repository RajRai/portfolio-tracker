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


def test_embedded_report_rewrite_serves_same_origin_html(monkeypatch, tmp_path):
    report_path = tmp_path / "report_0.html"
    report_path.write_text(
        """
<!doctype html>
<html>
<head><title>Report</title></head>
<body onload="save()"><div class="container">hello</div></body>
</html>
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "OUT_DIR", tmp_path)

    response = server.app.test_client().get(
        "/reports/report_0.html?embed=1&mode=dark&bg=%230f0f0f&paper=%23171717&text=%23ffffff&divider=rgba(255,255,255,0.12)&hover=rgba(255,255,255,0.08)"
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "onload=" not in html
    assert "<base target=\"_blank\" />" in html
    assert ":root { color-scheme: dark; }" in html
    assert "background: #0f0f0f !important;" in html
