import json

from src import server


def test_frontend_deep_link_serves_react_index(monkeypatch, tmp_path):
    index_path = tmp_path / "index.html"
    index_path.write_text("<!doctype html><div id=\"root\"></div>", encoding="utf-8")
    monkeypatch.setattr(server, "CLIENT_DIR", tmp_path)

    response = server.app.test_client().get("/tools/market-cap-weights")

    assert response.status_code == 200
    assert b'<div id="root"></div>' in response.data


def test_frontend_algo_output_deep_link_serves_react_index(monkeypatch, tmp_path):
    index_path = tmp_path / "index.html"
    index_path.write_text("<!doctype html><div id=\"root\"></div>", encoding="utf-8")
    monkeypatch.setattr(server, "CLIENT_DIR", tmp_path)

    response = server.app.test_client().get("/tools/algo-output-processor")

    assert response.status_code == 200
    assert b'<div id="root"></div>' in response.data


def test_frontend_model_portfolio_deep_link_serves_react_index(monkeypatch, tmp_path):
    index_path = tmp_path / "index.html"
    index_path.write_text("<!doctype html><div id=\"root\"></div>", encoding="utf-8")
    monkeypatch.setattr(server, "CLIENT_DIR", tmp_path)

    response = server.app.test_client().get("/tools/model-portfolio-report")

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


def test_algo_output_processor_endpoint_returns_json(monkeypatch):
    monkeypatch.setattr(
        server,
        "algo_output_processor",
        lambda raw_text, api_key=None: {
            "groups": {"buy": ["CEF"], "sell": [], "hold": []},
            "summary": {"total": 1, "buy": 1, "sell": 0, "hold": 0, "unpriced": 0},
            "warnings": [],
        },
    )

    response = server.app.test_client().post(
        "/api/tools/algo-output-processor",
        json={"rawText": "Ticker,TargetBuyPrice,TargetSellPrice\nCEF,1,2"},
    )

    assert response.status_code == 200
    assert response.get_json()["groups"]["buy"] == ["CEF"]


def test_load_accounts_sorts_using_canonical_account_order(monkeypatch, tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "accounts.json").write_text(
        json.dumps(
            [
                {"id": "legacy-retirement", "name": "Retirement"},
                {"id": "legacy-optical", "name": "Optical"},
                {"id": "legacy-cloud", "name": "Cloud"},
            ]
        ),
        encoding="utf-8",
    )

    data_accounts = tmp_path / "accounts.json"
    data_accounts.write_text(
        json.dumps(
            [
                {"id": "OPTICAL", "name": "Optical"},
                {"id": "CLOUD", "name": "Cloud"},
                {"id": "RETIREMENT", "name": "Retirement"},
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(server, "OUT_DIR", out_dir)
    monkeypatch.setattr(server, "DATA_ACCOUNTS_FILE", data_accounts)

    accounts = server._load_accounts()

    assert [account["name"] for account in accounts] == ["Optical", "Cloud", "Retirement"]
