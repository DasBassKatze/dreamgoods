from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import select

from dreamgoods import db
from dreamgoods.ai import polza
from dreamgoods.api.routers import textile as router
from dreamgoods.core import storage
from dreamgoods.core.auth import CurrentUser
from dreamgoods.db.models import Job
from dreamgoods.services import projects, textile
from dreamgoods.workers import queue


def picture(color):
    out = BytesIO()
    Image.new("RGB", (30, 40), color).save(out, format="PNG")
    return out.getvalue()


def test_textile_uses_two_references_and_keeps_result_in_project(database, monkeypatch, tmp_path):
    _, ids = database
    pid = ids["project"]
    monkeypatch.setattr(storage.config, "STORAGE_DIR", tmp_path)
    calls = []

    def generate(settings, key, prompt, references, tag):
        calls.append((settings, prompt, references))
        return {}

    result = picture("green")
    monkeypatch.setattr(polza, "generate", generate)
    monkeypatch.setattr(polza, "extract_image", lambda _: result)
    garment, swatch = picture("blue"), picture("black")

    with pytest.raises(ValueError, match="JPEG"):
        textile.start(pid, b"not an image", swatch)

    job = textile.start(pid, garment, swatch)
    assert job == textile.start(pid, garment, swatch)
    queue._run_handler(job["id"], "textile")
    queue._finish(job["id"], "done")

    assert len(calls) == 1
    settings, prompt, refs = calls[0]
    assert settings["aspect"] == "3:4"
    assert "Edit the first image" in prompt and "second image only" in prompt
    assert len(refs) == 2
    assert textile.latest(pid)["has_image"]
    user = CurrentUser(1, ids["org"], "client", "Client", "user", ids["client"])
    projects._storage_cache.pop(ids["client"], None)
    assert projects.storage_usage(user)["used"] == len(garment) + len(swatch) + len(result)
    with db.session() as s:
        assert len(s.scalars(select(Job).where(Job.kind == "textile")).all()) == 1
    assert router.image(job["id"], download=True, pid=pid).body == result
    with pytest.raises(LookupError):
        router.image(job["id"], pid=pid + 1)
