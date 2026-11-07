from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, model_validator

from ...core import auth
from ...services import assistant
from ..deps import project_id

router = APIRouter(prefix="/api/projects/{project_id}/assistant", tags=["помощник"])


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=10000)


class Question(BaseModel):
    message: str = Field(min_length=1, max_length=3000)
    history: list[Message] = Field(default_factory=list, max_length=10)
    route: str = Field("products", max_length=40)
    product_ids: list[int] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def bounded(self):
        if not self.message.strip():
            raise ValueError("Введите вопрос")
        if sum(len(m.content) for m in self.history) > 16000:
            raise ValueError("История слишком длинная — начните новый диалог")
        if any(i <= 0 for i in self.product_ids):
            raise ValueError("Некорректный товар")
        return self


@router.get("")
def config(request: Request, pid: int = Depends(project_id)):
    return assistant.config(pid, auth.user(request).master)


@router.post("")
def ask(body: Question, request: Request, pid: int = Depends(project_id)):
    return assistant.reply(pid, auth.user(request), body)
