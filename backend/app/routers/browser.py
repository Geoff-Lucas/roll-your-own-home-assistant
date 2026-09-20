import logging

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlmodel import select

from ..browser import cdp
from ..browser.controller import BrowserUnavailable, controller
from ..browser.urls import is_web_url
from ..db import SessionDep
from ..models import Recipe
from ..recipes.importer import import_recipe_from_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/browser", tags=["browser"])


class Rect(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class Navigate(BaseModel):
    address: str = Field(max_length=2000)


async def _guarded(action):
    """Run a controller action, translating its failures into HTTP errors:
    503 when the browser can't run here at all, 502 when it's running but
    didn't do what was asked, 400 for a bad address."""
    try:
        return await action()
    except BrowserUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except cdp.CDPError as exc:
        logger.warning("Browser command failed: %s", exc)
        raise HTTPException(status_code=502, detail="The browser didn't respond") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/state")
async def get_state() -> dict:
    return await _guarded(controller.state)


@router.post("/show")
async def show(rect: Rect) -> dict:
    async def action():
        await controller.show(rect.x, rect.y, rect.width, rect.height)
        return await controller.state()

    return await _guarded(action)


@router.post("/hide", status_code=204)
async def hide() -> None:
    await _guarded(controller.hide)


@router.post("/navigate")
async def navigate(payload: Navigate) -> dict:
    async def action():
        await controller.navigate(payload.address)
        return await controller.state()

    return await _guarded(action)


@router.post("/back")
async def back() -> dict:
    async def action():
        await controller.back()
        return await controller.state()

    return await _guarded(action)


@router.post("/forward")
async def forward() -> dict:
    async def action():
        await controller.forward()
        return await controller.state()

    return await _guarded(action)


@router.post("/reload")
async def reload() -> dict:
    async def action():
        await controller.reload()
        return await controller.state()

    return await _guarded(action)


@router.post("/import-current", response_model=Recipe, status_code=201)
async def import_current_page(session: SessionDep) -> Recipe:
    """Send whatever page the browser is showing through the recipe importer.
    The URL is read server-side over DevTools — the frontend couldn't read it
    itself, since the page lives in a separate window."""
    url = await _guarded(controller.current_url)
    if not url or not is_web_url(url):
        raise HTTPException(status_code=400, detail="Open a recipe page in the browser first")

    existing = session.exec(select(Recipe).where(Recipe.source_url == url)).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"“{existing.title}” is already in your recipes")

    try:
        recipe = await run_in_threadpool(import_recipe_from_url, url)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Couldn't find a recipe on this page: {exc}") from exc
    session.add(recipe)
    session.commit()
    session.refresh(recipe)
    return recipe
