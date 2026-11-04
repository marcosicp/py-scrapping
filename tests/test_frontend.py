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
        assert f'data-slug="{cls.slug}"' in html, f"missing card {cls.slug}"
        assert cls.label in html, f"missing label {cls.label}"


def test_scrape_buttons_use_the_scraper_api_not_the_legacy_aliases(client):
    """The cards used to POST /scraping-<slug>; those are deprecated aliases."""
    html = client.get("/scrape").data.decode("utf-8")
    assert '"/api/scrapers"' in html
    assert "/start" in html and "/stop" in html
    assert "/scraping-" not in html


def test_scrape_offers_a_select_per_scraper_that_accepts_categories(client):
    html = client.get("/scrape").data.decode("utf-8")
    with_categories = [cls for cls in default_registry().classes()
                       if cls.categories]
    assert html.count('data-role="category"') == len(with_categories)
    for cls in with_categories:
        for categoria in cls.categories:
            assert f'<option value="{categoria}">{categoria}</option>' in html


def test_scrape_loads_no_third_party_asset(client):
    """Admin page: no CDN, no jQuery, no Bootstrap, no Tailwind, no SRI-less
    socket.io client. The whole page is one self-contained document."""
    html = client.get("/scrape").data.decode("utf-8").lower()
    # Library names can never appear: the page has no dependency at all.
    for forbidden in ("cdnjs", "googleapis", "bootstrapcdn", "jquery",
                      "bootstrap", "tailwind", "socket.io", "integrity=",
                      "crossorigin", "https://", "http://"):
        assert forbidden not in html, f"third-party asset leaked: {forbidden}"
    # A remote asset would need an absolute or protocol-relative URL.
    assert 'src="//' not in html
    assert 'href="//' not in html


def test_scrape_does_not_reference_a_stylesheet_that_never_existed(client):
    """`static/assets/style.css` was a permanent 404: static/ is the Angular
    build output, so the page carries its own <style> block instead."""
    html = client.get("/scrape").data.decode("utf-8")
    assert "assets/style.css" not in html
    assert "<style>" in html


def test_scrape_is_a_valid_document_with_explicit_encoding_and_viewport(client):
    html = client.get("/scrape").data.decode("utf-8")
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert '<meta charset="utf-8">' in html
    assert 'name="viewport"' in html
    assert '<html lang="es">' in html


def test_scrape_uses_relative_urls_only(client):
    html = client.get("/scrape").data.decode("utf-8")
    assert "127.0.0.1" not in html
    assert "http://" not in html
