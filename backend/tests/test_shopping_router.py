from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.models import MealPlan, Recipe, ShoppingItem
from app.routers import shopping as shopping_module

WEDNESDAY = date(2026, 9, 23)  # the week is Sun 9/20 to Sat 9/26


def item(name, quantity=None):
    return {"raw_text": f"{quantity or ''} {name}".strip(), "name": name, "quantity_text": quantity}


@pytest.fixture
def setup(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(shopping_module.router)
    app.dependency_overrides[get_session] = override_get_session

    today = {"is": WEDNESDAY}
    monkeypatch.setattr(shopping_module, "local_today", lambda: today["is"])

    with Session(engine) as session:
        session.add(Recipe(id=1, title="Tacos", ingredients=[item("yellow onion", "1"), item("ground beef", "1 lb")]))
        session.add(Recipe(id=2, title="Pot roast", ingredients=[item("yellow onion", "2"), item("chuck roast", "3 lb")]))
        session.add(Recipe(id=3, title="Pasta", ingredients=[item("spaghetti", "1 lb")]))
        session.add(
            Recipe(
                id=4,
                title="Steak night",
                ingredients=[item("steak", "2 lb"), item("kosher salt", "1 tsp"), item("freshly ground black pepper"), item("bell peppers", "2")],
            )
        )
        session.commit()

    def plan(day: date, recipe_id: int):
        with Session(engine) as session:
            session.add(MealPlan(plan_date=day, recipe_id=recipe_id))
            session.commit()

    return TestClient(app), engine, plan, today


def names(body):
    return [entry["name"] for entry in body["items"]]


def test_an_empty_plan_gives_an_empty_list(setup):
    client, *_ = setup

    body = client.get("/shopping-list").json()

    assert body["items"] == [] and body["meals"] == 0
    assert (body["start"], body["end"]) == ("2026-09-23", "2026-09-26")


def test_it_covers_today_through_saturday_only(setup):
    client, _, plan, _ = setup
    plan(date(2026, 9, 21), 3)  # Monday: already eaten
    plan(date(2026, 9, 23), 1)  # today
    plan(date(2026, 9, 25), 2)  # Friday
    plan(date(2026, 9, 27), 3)  # next Sunday: next week's list

    body = client.get("/shopping-list").json()

    assert body["meals"] == 2
    assert names(body) == ["chuck roast", "ground beef", "yellow onion"]  # no spaghetti


def test_the_same_ingredient_is_one_line_showing_which_meals_need_it(setup):
    client, _, plan, _ = setup
    plan(date(2026, 9, 23), 1)
    plan(date(2026, 9, 25), 2)

    onion = next(entry for entry in client.get("/shopping-list").json()["items"] if entry["name"] == "yellow onion")

    assert onion["quantity"] == "3"
    assert onion["recipes"] == ["Tacos", "Pot roast"]
    assert onion["checked"] is False and onion["manual"] is False


def test_ticking_an_item_off_sticks_and_can_be_undone(setup):
    client, _, plan, _ = setup
    plan(date(2026, 9, 23), 1)
    key = client.get("/shopping-list").json()["items"][0]["key"]

    assert client.put("/shopping-list/checked", json={"key": key, "checked": True}).status_code == 204
    assert client.put("/shopping-list/checked", json={"key": key, "checked": True}).status_code == 204  # twice is fine
    ticked = [entry["checked"] for entry in client.get("/shopping-list").json()["items"]]
    assert ticked == [True, False]

    client.put("/shopping-list/checked", json={"key": key, "checked": False})
    assert [entry["checked"] for entry in client.get("/shopping-list").json()["items"]] == [False, False]


def test_ticks_do_not_carry_over_into_next_week(setup):
    client, engine, plan, today = setup
    plan(date(2026, 9, 23), 1)
    plan(date(2026, 9, 28), 1)  # next Monday: onions again
    onion_key = next(e["key"] for e in client.get("/shopping-list").json()["items"] if e["name"] == "yellow onion")
    client.put("/shopping-list/checked", json={"key": onion_key, "checked": True})

    today["is"] = date(2026, 9, 28)  # a new week
    body = client.get("/shopping-list").json()

    assert [e["checked"] for e in body["items"] if e["name"] == "yellow onion"] == [False]
    with Session(engine) as session:  # and last week's tick is tidied away
        assert session.exec(select(ShoppingItem)).all() == []


def test_an_item_added_by_hand_stays_until_it_is_removed_whatever_the_week(setup):
    client, _, _, today = setup

    added = client.post("/shopping-list/manual", json={"name": "  paper   towels "}).json()
    assert (added["name"], added["manual"], added["checked"]) == ("paper towels", True, False)

    client.put("/shopping-list/checked", json={"key": added["key"], "checked": True})
    today["is"] = date(2026, 9, 30)  # next week
    kept = client.get("/shopping-list").json()["items"]
    assert [(e["name"], e["checked"], e["manual"]) for e in kept] == [("paper towels", True, True)]

    assert client.delete(f"/shopping-list/manual/{added['key']}").status_code == 204
    assert client.get("/shopping-list").json()["items"] == []


def test_a_blank_item_is_refused(setup):
    client, *_ = setup

    assert client.post("/shopping-list/manual", json={"name": "   "}).status_code == 422


def test_unknown_items_are_a_404_not_a_silent_success(setup):
    client, *_ = setup

    assert client.put("/shopping-list/checked", json={"key": "manual:nope", "checked": True}).status_code == 404
    assert client.delete("/shopping-list/manual/manual:nope").status_code == 404


@pytest.fixture
def sent(monkeypatch):
    """What the QR code's email is built from, captured as it's made."""
    seen = {}
    real = shopping_module.build_mailto

    def spy(entries, header, to="", *args, **kwargs):
        seen.update(entries=list(entries), header=header, to=to)
        return real(entries, header, to, *args, **kwargs)

    monkeypatch.setattr(shopping_module, "build_mailto", spy)
    return seen


def share(client, exclude="default"):
    """Ask for the phone message; `exclude` left alone is the starting choice."""
    return client.post("/shopping-list/share", json={} if exclude == "default" else {"exclude": exclude}).json()


def by_name(body):
    return {entry["name"]: entry["included"] for entry in body["items"]}


def test_the_qr_code_carries_what_is_left_to_buy(setup, sent, monkeypatch):
    client, _, plan, _ = setup
    monkeypatch.setattr(shopping_module.settings, "shopping_email_to", "me@example.com")
    plan(date(2026, 9, 23), 1)
    plan(date(2026, 9, 25), 2)
    client.post("/shopping-list/manual", json={"name": "paper towels"})
    onion = next(i["key"] for i in client.get("/shopping-list").json()["items"] if i["name"] == "yellow onion")
    client.put("/shopping-list/checked", json={"key": onion, "checked": True})

    body = share(client)

    assert body["qr"].startswith("data:image/svg+xml")
    assert (body["included"], body["left_out"]) == (3, 0)
    # Ticked items are already in the trolley, so they're neither offered nor in the message.
    assert by_name(body) == {"chuck roast": True, "ground beef": True, "paper towels": True}
    assert sent["entries"] == ["- Chuck roast: 3 lb", "- Ground beef: 1 lb", "- Paper towels"]
    assert sent["header"] == "Shopping list, Sep 23 - Sep 26"
    assert sent["to"] == "me@example.com"


def test_salt_and_pepper_start_out_left_off_the_message(setup, sent):
    client, _, plan, _ = setup
    plan(date(2026, 9, 23), 4)

    body = share(client)

    # Offered, so they can be put back, but not ticked to begin with. Bell peppers aren't pepper.
    assert by_name(body) == {"steak": True, "kosher salt": False, "freshly ground black pepper": False, "bell peppers": True}
    assert sent["entries"] == ["- Bell peppers: 2", "- Steak: 2 lb"]
    assert body["included"] == 2


def test_anything_can_be_put_back_or_dropped(setup, sent):
    client, _, plan, _ = setup
    plan(date(2026, 9, 23), 4)
    keys = {entry["name"]: entry["key"] for entry in share(client)["items"]}

    everything = share(client, exclude=[])  # an empty choice means leave nothing out, salt included
    assert all(by_name(everything).values()) and everything["included"] == 4

    no_steak = share(client, exclude=[keys["steak"]])  # a choice replaces the starting one: salt is back in
    assert by_name(no_steak) == {"steak": False, "kosher salt": True, "freshly ground black pepper": True, "bell peppers": True}
    assert "- Steak: 2 lb" not in sent["entries"] and "- Kosher salt: 1 tsp" in sent["entries"]


def test_something_typed_in_by_hand_is_never_taken_for_a_staple(setup):
    client, *_ = setup
    client.post("/shopping-list/manual", json={"name": "salt"})

    assert by_name(share(client)) == {"salt": True}


def test_with_nothing_chosen_there_is_no_code_but_the_items_are_still_offered(setup):
    client, _, plan, _ = setup
    plan(date(2026, 9, 23), 3)
    key = client.get("/shopping-list").json()["items"][0]["key"]

    body = share(client, exclude=[key])

    assert body["qr"] is None and (body["included"], body["left_out"]) == (0, 0)
    assert by_name(body) == {"spaghetti": False}


def test_with_everything_ticked_or_nothing_planned_there_is_nothing_to_offer(setup):
    client, _, plan, _ = setup
    assert share(client) == {"items": [], "qr": None, "included": 0, "left_out": 0}

    plan(date(2026, 9, 23), 3)
    key = client.get("/shopping-list").json()["items"][0]["key"]
    client.put("/shopping-list/checked", json={"key": key, "checked": True})

    assert share(client)["items"] == []


def test_a_very_long_list_still_gives_a_code_and_says_what_it_left_out(setup):
    client, engine, plan, _ = setup
    with Session(engine) as session:
        session.add(Recipe(id=9, title="Feast", ingredients=[item(f"ingredient number {n}", "1 1/2 cups") for n in range(150)]))
        session.commit()
    plan(date(2026, 9, 23), 9)

    body = share(client)

    assert body["qr"].startswith("data:image/svg+xml")
    assert len(body["items"]) == 150  # all offered; the message holds as many as fit
    assert body["left_out"] > 0 and body["included"] + body["left_out"] == 150


def test_only_hand_added_items_can_be_removed(setup):
    client, _, plan, _ = setup
    plan(date(2026, 9, 23), 1)
    key = client.get("/shopping-list").json()["items"][0]["key"]

    assert client.delete(f"/shopping-list/manual/{key}").status_code == 404  # an ingredient follows the plan instead
