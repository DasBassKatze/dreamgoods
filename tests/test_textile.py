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

    def generate(settings, key, prompt, references, tag, *, should_stop):
        assert not should_stop()
        calls.append((settings, prompt, references))
        return {}

    result = picture("green")
    monkeypatch.setattr(polza, "generate", generate)
    monkeypatch.setattr(polza, "extract_image", lambda _: result)
    garment, swatch = picture("blue"), picture("black")

    with pytest.raises(ValueError, match="JPEG"):
        textile.start(pid, b"not an image", swatch)

    job = textile.start(pid, garment, swatch, "  Оставь рукава без изменений  ")
    assert job == textile.start(pid, garment, swatch)
    queue._run_handler(job["id"], "textile")
    queue._finish(job["id"], "done")

    assert len(calls) == 1
    settings, prompt, refs = calls[0]
    assert settings["aspect"] == "3:4"
    assert "Edit the first image" in prompt and "second image only" in prompt
    assert prompt.endswith("Оставь рукава без изменений")
    assert len(refs) == 2
    assert textile.latest(pid) == {"job": {"id": job["id"], "status": "done", "error": "", "has_image": True},
                                  "result_id": job["id"]}
    user = CurrentUser(1, ids["org"], "client", "Client", "user", ids["client"])
    projects._storage_cache.pop(ids["client"], None)
    assert projects.storage_usage(user)["used"] == len(garment) + len(swatch) + len(result)
    with db.session() as s:
        assert len(s.scalars(select(Job).where(Job.kind == "textile")).all()) == 1
    download = router.image(job["id"], download=True, pid=pid)
    assert download.body == result
    assert download.headers["content-type"] == "image/png"
    assert download.headers["content-disposition"] == f'attachment; filename="textile-transfer-{job["id"]}.png"'
    with pytest.raises(LookupError):
        router.image(job["id"], pid=pid + 1)
    assert textile.cancel(pid, job["id"]) == textile.latest(pid)["job"]
    second = textile.start(pid, garment, swatch)
    router.cancel(second["id"], pid=pid)
    assert router.latest(pid)["result_id"] == job["id"]
    assert router.latest(pid + 1)["result_id"] is None


@pytest.mark.parametrize("provider_error", [False, True])
def test_cancel_textile_in_queue_and_during_generation(database, monkeypatch, tmp_path, provider_error):
    _, ids = database
    pid = ids["project"]
    monkeypatch.setattr(storage.config, "STORAGE_DIR", tmp_path)
    garment, swatch = picture("blue"), picture("black")
    queued = textile.start(pid, garment, swatch)["id"]
    with pytest.raises(LookupError):
        router.cancel(queued, pid=pid + 1)
    assert router.cancel(queued, pid=pid)["status"] == "cancelled"
    running = textile.start(pid, garment, swatch)["id"]
    assert running != queued
    with db.session() as s:
        s.get(Job, running).status = "running"

    def generate(settings, key, prompt, references, tag, *, should_stop):
        assert not should_stop()
        assert router.cancel(running, pid=pid)["status"] == "cancelling"
        assert should_stop()
        if provider_error:
            raise RuntimeError("provider failed")
        return {}

    monkeypatch.setattr(polza, "generate", generate)
    monkeypatch.setattr(polza, "extract_image", lambda _: pytest.fail("Cancelled output was downloaded"))
    if provider_error:
        with pytest.raises(RuntimeError, match="provider failed"):
            queue._run_handler(running, "textile")
        queue._finish(running, "error", "provider failed")
    else:
        queue._run_handler(running, "textile")
        queue._finish(running, "done")
    assert textile.latest(pid) == {"job": {"id": running, "status": "cancelled", "error": "", "has_image": False},
                                  "result_id": None}
    with pytest.raises(LookupError):
        router.image(running, pid=pid)
