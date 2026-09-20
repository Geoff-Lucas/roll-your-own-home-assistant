from app.recipes import importer


class FakeScraper:
    def title(self):
        return "Spinach and Feta Turkey Burgers"

    def ingredients(self):
        return ["2 pounds ground turkey", "4 ounces feta cheese"]

    def instructions_list(self):
        return ["Mix everything together.", "Grill until done."]

    def image(self):
        return "https://example.com/burger.jpg"

    def prep_time(self):
        return 20

    def cook_time(self):
        return 15

    def yields(self):
        return "8 servings"

    def dietary_restrictions(self):
        raise RuntimeError("no dietary data in schema.org for this site")


def test_import_recipe_maps_scraper_fields(monkeypatch):
    monkeypatch.setattr(importer, "scrape_me", lambda url: FakeScraper())

    recipe = importer.import_recipe_from_url("https://example.com/recipe")

    assert recipe.title == "Spinach and Feta Turkey Burgers"
    assert recipe.source_url == "https://example.com/recipe"
    assert recipe.source_image_url == "https://example.com/burger.jpg"
    assert recipe.image_path is None  # never downloaded at import time
    assert recipe.steps == ["Mix everything together.", "Grill until done."]
    assert recipe.prep_time_minutes == 20
    assert recipe.cook_time_minutes == 15
    assert recipe.servings == 8
    # dietary_restrictions() raised — falls back to empty, doesn't blow up the import
    assert recipe.dietary_tags == []

    assert len(recipe.ingredients) == 2
    assert recipe.ingredients[0]["raw_text"] == "2 pounds ground turkey"
    assert recipe.ingredients[0]["name"] == "ground turkey"
    assert recipe.ingredients[0]["quantity_text"] == "2 pounds"


def test_import_recipe_falls_back_when_title_missing(monkeypatch):
    class NoTitleScraper(FakeScraper):
        def title(self):
            raise RuntimeError("no title found")

    monkeypatch.setattr(importer, "scrape_me", lambda url: NoTitleScraper())

    recipe = importer.import_recipe_from_url("https://example.com/recipe")

    assert recipe.title == "https://example.com/recipe"
