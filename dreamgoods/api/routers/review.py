from typing import Literal
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from ...services import frames, review_board
from ..deps import project_id, need_key

router = APIRouter(prefix="/api/projects/{project_id}/review", tags=["приёмка"])

class Item(BaseModel):
    frame_id: int
    generation_id: int

class Batch(BaseModel):
    items: list[Item] = Field(min_length=1, max_length=100)
    action: Literal["accept", "reject", "edit"]
    comment: str = Field("", max_length=1500)

@router.get("")
def listing(pid: int = Depends(project_id), page: int = Query(1, ge=1),
            status: Literal["review", "unchecked", "pass", "accepted", "all"] = "review",
            defect: Literal["", "identity", "quantity", "anatomy", "text", "composition", "technical"] = "", query: str = ""):
    return review_board.listing(pid, page, status, defect, query)

@router.post("/batch")
def batch(body: Batch, pid: int = Depends(project_id)):
    if body.action == "edit":
        need_key(pid)
        if len(body.comment.strip()) < 3:
            raise ValueError("опишите правку")
    done, errors = [], []
    for item in {i.frame_id: i for i in body.items}.values():
        try:
            if body.action == "edit":
                frames.edit(pid, item.frame_id, body.comment, item.generation_id, expected_generation=item.generation_id)
            else:
                frames.review(pid, item.frame_id, "ok" if body.action == "accept" else "bad", body.comment, False,
                    expected_generation=item.generation_id)
            done.append(item.frame_id)
        except (ValueError, LookupError) as e:
            errors.append({"frame_id": item.frame_id, "error": str(e)})
    return {"done": done, "errors": errors}
