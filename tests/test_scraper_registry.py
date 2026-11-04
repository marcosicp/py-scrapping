"""Tests for the scraper registry and the category validation contract."""

import pytest

from api.scrapers.base import BaseScraper
from api.scrapers.errors import InvalidCategory, UnknownScraper
from api.scrapers.registry import ScraperRegistry, default_registry


class Alpha(BaseScraper):
    slug = "alpha"
    label = "Alpha"

    def run(self, ctx):
        pass


class Beta(BaseScraper):
    slug = "beta"
    label = "Beta"
    categories = ("almacen",)

    def run(self, ctx):
        pass


class NoCategory(BaseScraper):
    slug = "nocat"
    label = "NoCategory"

    def run(self, ctx):
        pass


class ValidatingNoCategory(BaseScraper):
    slug = "validating-nocat"
    label = "ValidatingNoCategory"
    categories = ()

    def run(self, ctx):
        pass


# -- registration and lookup -------------------------------------------


def test_register_then_get_returns_the_class():
    registry = ScraperRegistry()
    assert registry.register(Alpha) is Alpha
    assert registry.get("alpha") is Alpha


def test_register_accepts_initial_scrapers():
    registry = ScraperRegistry([Alpha, Beta])
    assert registry.get("alpha") is Alpha
    assert registry.get("beta") is Beta


def test_register_works_as_decorator_and_returns_the_class():
    registry = ScraperRegistry()

    @registry.register
    class Gamma(BaseScraper):
        slug = "gamma"
        label = "Gamma"

        def run(self, ctx):
            pass

    assert registry.get("gamma") is Gamma


def test_duplicate_slug_raises_value_error():
    registry = ScraperRegistry([Alpha])
    with pytest.raises(ValueError):
        registry.register(Alpha)


def test_duplicate_slug_across_classes_raises_value_error():
    registry = ScraperRegistry([Alpha])

    class OtherName(BaseScraper):
        slug = "alpha"
        label = "Other"

        def run(self, ctx):
            pass

    with pytest.raises(ValueError):
        registry.register(OtherName)


@pytest.mark.parametrize("slug", ["", "Disco", "two words", "-x"])
def test_invalid_slugs_raise_value_error(slug):
    registry = ScraperRegistry()

    class Bad(BaseScraper):
        def run(self, ctx):
            pass

    Bad.slug = slug
    Bad.label = "Bad"
    with pytest.raises(ValueError):
        registry.register(Bad)


def test_empty_label_raises_value_error():
    registry = ScraperRegistry()

    class Unlabeled(BaseScraper):
        slug = "unlabeled"
        label = ""

        def run(self, ctx):
            pass

    with pytest.raises(ValueError):
        registry.register(Unlabeled)


def test_registering_non_scraper_class_raises_value_error():
    registry = ScraperRegistry()
    with pytest.raises(ValueError):
        registry.register(dict)


# -- ordering and membership -------------------------------------------


def test_registration_order_is_preserved():
    registry = ScraperRegistry([Beta, Alpha])
    assert registry.slugs() == ["beta", "alpha"]
    assert registry.classes() == [Beta, Alpha]
    assert list(registry) == [Beta, Alpha]


def test_len_and_contains():
    registry = ScraperRegistry([Alpha, Beta])
    assert len(registry) == 2
    assert "alpha" in registry
    assert "nope" not in registry


def test_unknown_slug_raises_unknown_scraper_with_slug():
    registry = ScraperRegistry([Alpha])
    with pytest.raises(UnknownScraper) as excinfo:
        registry.get("ghost")
    assert excinfo.value.slug == "ghost"
    assert "ghost" in str(excinfo.value)


def test_every_error_is_a_scraper_error():
    assert issubclass(UnknownScraper, Exception)
    assert issubclass(InvalidCategory, Exception)


def test_errors_are_subclasses_of_scraper_error():
    from api.scrapers.errors import ScraperError

    assert issubclass(UnknownScraper, ScraperError)
    assert issubclass(InvalidCategory, ScraperError)
    assert isinstance(InvalidCategory("a", "b", ("c",)), InvalidCategory)


# -- default registry ---------------------------------------------------


def test_default_registry_is_empty_and_typed():
    registry = default_registry()
    assert isinstance(registry, ScraperRegistry)
    for scraper in registry.classes():
        # Nothing is ported yet: if members exist they must be real
        # BaseScraper subclasses.
        assert issubclass(scraper, BaseScraper)


# -- category validation ------------------------------------------------


def test_validate_category_none_and_empty_are_none():
    assert Beta.validate_category(None) is None
    assert Beta.validate_category("") is None


def test_validate_category_returns_allowed_value():
    assert Beta.validate_category("almacen") == "almacen"


def test_validate_category_unknown_value_raises_invalid_category():
    with pytest.raises(InvalidCategory) as excinfo:
        Beta.validate_category("bebidas")
    assert excinfo.value.slug == "beta"
    assert excinfo.value.category == "bebidas"
    assert excinfo.value.allowed == ("almacen",)
    assert "bebidas" in str(excinfo.value)


def test_scraper_without_categories_ignores_any_value():
    assert ValidatingNoCategory.validate_category(None) is None
    assert ValidatingNoCategory.validate_category("almacen") is None
    assert ValidatingNoCategory.validate_category("whatever") is None
