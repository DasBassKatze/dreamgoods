from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from typing import Literal
from ...core import auth
from ...services import preflight, trials, frames, moderation, plans
from ..deps import project_id, need_key

router=APIRouter(prefix='/api/projects/{project_id}',tags=['подготовка и приёмка'])

class Products(BaseModel):
    product_ids:list[int]|None=Field(None,max_length=5000)

class Approval(BaseModel):
    generation_id:int

class Decision(BaseModel):
    frame_id:int
    generation_id:int

class BatchReview(BaseModel):
    items:list[Decision]=Field(min_length=1,max_length=100)
    verdict:Literal['ok','bad']
    comment:str=Field('',max_length=1500)
    regen:bool=False

@router.post('/preflight')
def inspect(body:Products,pid:int=Depends(project_id)):
    return preflight.inspect_sources(pid,body.product_ids)

@router.get('/trial')
def current(pid:int=Depends(project_id)):
    return {'trial':trials.latest(pid)}

@router.post('/trial')
def start(body:Products,request:Request,pid:int=Depends(project_id)):
    need_key(pid)
    plans.check_generation_project(pid,body.product_ids)
    moderation.guard_products(pid,body.product_ids)
    return {'trial':trials.start(pid,body.product_ids)}

@router.post('/trial/{job_id}/approve')
def approve(job_id:int,body:Approval,pid:int=Depends(project_id)):
    need_key(pid)
    ids=trials.product_ids(pid,job_id)
    plans.check_generation_project(pid,ids)
    moderation.guard_products(pid,ids)
    return trials.approve(pid,job_id,body.generation_id)

@router.post('/review/batch')
def review(body:BatchReview,request:Request,pid:int=Depends(project_id)):
    if body.regen and body.verdict=='bad':
        need_key(pid)
        plans.check_generation_project(pid)
        moderation.guard('замечание к кадру',body.comment,project_id=pid,user=auth.user(request))
    results=[]
    for item in body.items:
        try:
            frames.review(pid,item.frame_id,body.verdict,body.comment.strip(),body.regen,expected_generation=item.generation_id)
            results.append({'frame_id':item.frame_id,'ok':True})
        except (ValueError,LookupError,PermissionError) as e:
            results.append({'frame_id':item.frame_id,'ok':False,'error':str(e)})
    return {'results':results}
