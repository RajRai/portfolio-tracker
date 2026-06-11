import json
from types import SimpleNamespace

from src import posthog_analytics
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
        lambda raw_text, api_key=None, **kwargs: {
            "priceSignals": {
                "groups": {"buy": ["CEF"], "sell": [], "hold": []},
                "summary": {"total": 1, "buy": 1, "sell": 0, "hold": 0, "unpriced": 0},
                "warnings": [],
            },
            "portfolioSignals": None,
            "warnings": [],
        },
    )

    response = server.app.test_client().post(
        "/api/tools/algo-output-processor",
        json={"rawText": "Ticker,TargetBuyPrice,TargetSellPrice\nCEF,1,2"},
    )

    assert response.status_code == 200
    assert response.get_json()["priceSignals"]["groups"]["buy"] == ["CEF"]


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


def test_posthog_config_endpoint_is_disabled_without_token(monkeypatch):
    monkeypatch.delenv("POSTHOG_PROJECT_TOKEN", raising=False)
    monkeypatch.delenv("POSTHOG_UI_HOST", raising=False)
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("POSTHOG_DEBUG", "false")
    monkeypatch.setenv("POSTHOG_RESPECT_DNT", "false")

    response = server.app.test_client().get("/api/posthog/config", base_url="https://portfolio.test")

    assert response.status_code == 200
    assert response.get_json() == {
        "enabled": False,
        "apiHost": "/api/posthog",
        "projectToken": "",
        "uiHost": "https://us.posthog.com",
        "debug": False,
        "respectDnt": False,
    }


def test_posthog_config_endpoint_can_enable_respect_dnt(monkeypatch):
    monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_test")
    monkeypatch.setenv("POSTHOG_RESPECT_DNT", "true")

    response = server.app.test_client().get("/api/posthog/config")

    assert response.status_code == 200
    assert response.get_json()["respectDnt"] is True


def test_posthog_proxy_forwards_requests(monkeypatch):
    captured = {}

    def fake_request(method, url, params=None, data=None, headers=None, allow_redirects=None, timeout=None):
        captured.update(
            {
                "method": method,
                "url": url,
                "params": params,
                "data": data,
                "headers": headers,
                "allow_redirects": allow_redirects,
                "timeout": timeout,
            }
        )
        return SimpleNamespace(
            status_code=202,
            content=b'{"ok":true}',
            headers={
                "Content-Type": "application/json",
                "Cache-Control": "no-store",
                "X-Ignored": "skip-me",
            },
        )

    monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_test")
    monkeypatch.setenv("POSTHOG_HOST", "https://eu.i.posthog.com")
    monkeypatch.setattr(posthog_analytics.requests, "request", fake_request)

    response = server.app.test_client().post(
        "/api/posthog/decide/?v=3",
        data=b'{"token":"x"}',
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "pytest",
        },
    )

    assert response.status_code == 202
    assert response.get_json() == {"ok": True}
    assert captured == {
        "method": "POST",
        "url": "https://eu.i.posthog.com/decide/",
        "params": [("v", "3")],
        "data": b'{"token":"x"}',
        "headers": {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "pytest",
        },
        "allow_redirects": False,
        "timeout": (5, 30),
    }
    assert response.headers["Cache-Control"] == "no-store"


def test_build_backend_capture_payload_keeps_anonymous_context(monkeypatch):
    monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_test")

    payload = posthog_analytics.build_backend_capture_payload(
        {
            "X-PostHog-Distinct-Id": "anon-123",
            "X-PostHog-Session-Id": "session-456",
        },
        route="/api/tools/model-portfolio-report",
        success=True,
        status_code=200,
        duration_ms=187,
        extra_properties={
            "tool_name": "model_portfolio_report",
            "portfolio_holding_count": 14,
            "ignored": {"not": "json-safe"},
        },
    )

    assert payload == {
        "api_key": "phc_test",
        "event": "backend_api_request",
        "distinct_id": "anon-123",
        "properties": {
            "$process_person_profile": False,
            "$session_id": "session-456",
            "source": "backend",
            "route": "/api/tools/model-portfolio-report",
            "success": True,
            "status_code": 200,
            "duration_ms": 187,
            "tool_name": "model_portfolio_report",
            "portfolio_holding_count": 14,
        },
    }
