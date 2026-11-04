"""Frontend blueprint: `/` (SPA bundle guard) and `/scrape` (monitor page) — T3.

Moved verbatim from ``api/routes.py``; these tests pin the legacy responses.
"""


def test_missing_bundle_answers_503_text_plain(app, client, tmp_path):
    app.static_folder = str(tmp_path)  # exists but has no index.html
    response = client.get("/")
    assert response.status_code == 503
    assert response.headers["Content-Type"].startswith("text/plain")
    assert b"npm ci && npm run build" in response.data


def test_root_serves_index_html_from_static_folder(app, client, tmp_path):
    index = tmp_path / "index.html"
    index.write_text("<html>the app</html>", encoding="utf-8")
    app.static_folder = str(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert response.data == b"<html>the app</html>"


def test_scrape_renders_the_monitor_page(client):
    response = client.get("/scrape")
    assert response.status_code == 200
    assert b"Carga de datos" in response.data
