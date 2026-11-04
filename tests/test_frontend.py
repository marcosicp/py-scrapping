"""Frontend blueprint: `/` (SPA bundle guard) and `/scrape` (monitor page).

T3 pinned the legacy responses; T13 renders `/scrape` from the scraper
registry instead of the five hand-written cards.
"""

from api.scrapers.registry import default_registry


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


def test_scrape_renders_one_card_per_registered_scraper(client):
    response = client.get("/scrape")
    html = response.data.decode("utf-8")
    for cls in default_registry().classes():
        assert cls.slug in html, f"missing slug {cls.slug}"
        assert cls.label in html, f"missing label {cls.label}"
        assert f"/scraping-{cls.slug}" in html
        assert f"/scraping-{cls.slug}-stop" in html


def test_scrape_uses_relative_urls_only(client):
    html = client.get("/scrape").data.decode("utf-8")
    assert "127.0.0.1" not in html
    assert "http://" not in html
