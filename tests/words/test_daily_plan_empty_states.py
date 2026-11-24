"""The dashboard's empty plan copy follows the reasons and available actions."""
# ruff: noqa: RUF001 -- assertions use the Russian UI copy.
from typing import Any

import pytest
from bs4 import BeautifulSoup
from flask import Flask, render_template, url_for


def render_plan(app: Flask, plan: dict[str, Any], completion: dict[str, bool] | None = None) -> BeautifulSoup:
    with app.test_request_context("/dashboard"):
        return BeautifulSoup(render_template(
            "partials/unified_daily_plan.html", dashboard_today=True, unified_plan=plan,
            plan_completion=completion or {},
        ), "html.parser")


def optional_review(**fields: Any) -> dict[str, Any]:
    return {"id": "review", "kind": "grammar_review", "title": "Повтор глагола to be",
            "url": "/grammar-lab/practice/topic/1", **fields}


def test_paused_empty_plan_names_pause_and_links_to_catalog(app: Flask) -> None:
    page = render_plan(app, {"mode": "paused", "paused_until": "2026-11-25"})
    empty = page.select_one(".daily-plan__empty-state")
    assert empty.select_one("h1").get_text() == "План на паузе"
    assert empty.select_one("time")["datetime"] == "2026-11-25"
    assert empty.select_one("time").get_text() == "25.11.2026"
    with app.test_request_context():
        assert empty.select_one("a")["href"] == url_for("courses.catalog")
    assert "Завершите настройку" not in empty.get_text()
    assert "Выбери доступное занятие ниже" not in page.get_text()


def test_graduated_links_to_actual_available_optional_list(app: Flask) -> None:
    page = render_plan(app, {
        "mode": "unified", "graduated": True, "optional": [optional_review(id="done"), optional_review()],
        "setup": [{"kind": "setup_book", "title": "Выберите книгу", "url": "#book-select-modal"}],
    }, {"done": True})
    empty = page.select_one(".daily-plan__empty-state")
    assert empty.select_one("h1").get_text() == "Курс завершён"
    assert empty.select_one("a")["href"] == "#daily-plan-optional-list"
    assert page.select_one("#daily-plan-optional-list a")["href"] == "/grammar-lab/practice/topic/1"
    assert page.select_one('[data-section="setup-prominent"] a')["href"] == "#book-select-modal"
    assert "Завершите настройку" not in empty.get_text()


@pytest.mark.parametrize("optional,completion", [
    ([], {}),
    ([optional_review(completed=True)], {}),
    ([optional_review()], {"review": True}),
    ([optional_review(url=None)], {}),
])
def test_finished_course_links_to_catalog_when_review_is_unavailable(
    app: Flask, optional: list[dict[str, Any]], completion: dict[str, bool],
) -> None:
    page = render_plan(app, {"mode": "unified", "graduated": True, "optional": optional}, completion)
    empty_link = page.select_one(".daily-plan__empty-state a")
    with app.test_request_context():
        assert empty_link["href"] == url_for("courses.catalog")


@pytest.mark.parametrize("state", [{"mode": "paused"}, {"mode": "unified", "graduated": True}])
def test_secured_empty_day_keeps_celebration(app: Flask, state: dict[str, Any]) -> None:
    page = render_plan(app, {**state, "study_day": "2026-11-24", "day_secured": True})
    assert page.select_one(".today-header h1").get_text() == "На сегодня всё получилось!"
    assert page.select_one("#fox-complete-title").get_text() == "День выполнен!"
    assert page.select_one(".daily-plan__empty-state") is None


def test_novice_with_setup_and_blocked_plan_have_their_own_copy(app: Flask) -> None:
    novice = render_plan(app, {
        "mode": "unified",
        "setup": [{"kind": "setup_book", "title": "Выберите книгу", "url": "#book-select-modal"}],
    })
    assert "Завершите настройку ниже" in novice.select_one(".daily-plan__empty-state").get_text()
    assert novice.select_one('[data-section="setup-prominent"] a')["href"] == "#book-select-modal"

    blocked = render_plan(app, {
        "mode": "unified", "blocked_module": {"module_title": "Следующий модуль", "reasons": ["Наберите 80%"]},
        "optional": [optional_review()],
    })
    empty = blocked.select_one(".daily-plan__empty-state")
    assert "Следующий модуль" in empty.get_text()
    assert empty.select_one("li").get_text() == "Наберите 80%"
