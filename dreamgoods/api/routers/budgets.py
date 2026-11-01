from fastapi import APIRouter,Depends,Request
from pydantic import BaseModel,Field
from typing import Literal
from sqlalchemy import select
from ... import db
from ...core import auth,keys,config
from ...core.money import money
from ...db.models import PaidOperation,Job,Generation,Organization
from ...services import budgets,payments
from ...services.common import context
from ..deps import project_id

router=APIRouter(prefix='/api/projects/{project_id}/budgets',tags=['бюджеты'])

class Resume(BaseModel):
    budget_rub:float|None=Field(None,ge=0,le=1e9,allow_inf_nan=False)
    retry_budget_rub:float|None=Field(None,ge=0,le=1e9,allow_inf_nan=False)

class Reconcile(BaseModel):
    action:Literal['refresh','release','settle']
    cost:float=Field(0,ge=0,le=1e9,allow_inf_nan=False)
    note:str=Field('',max_length=1000)

@router.get('')
def listing(request:Request,pid:int=Depends(project_id)):
    return budgets.listing(pid,auth.user(request).master)

@router.post('/{batch_id}/resume')
def resume(batch_id:int,body:Resume,pid:int=Depends(project_id)):
    return budgets.resume(pid,batch_id,body.budget_rub,body.retry_budget_rub)

@router.post('/resume-unbatched')
def resume_unbatched(pid:int=Depends(project_id)):
    with db.session() as s:
        jobs=s.scalars(select(Job).where(Job.project_id==pid,Job.batch_id.is_(None),Job.status=='paused')
                       .with_for_update()).all()
        n=0
        for j in jobs:
            if j.frame_id and s.scalar(select(Generation.id).where(Generation.frame_id==j.frame_id,Generation.status=='pending').limit(1)):continue
            j.status,j.error,j.finished_at='queued','',None;n+=1
    return {'queued':n}

@router.post('/operations/{operation_id}/reconcile')
def reconcile(operation_id:str,body:Reconcile,request:Request,pid:int=Depends(project_id)):
    cu=auth.master(request)
    with db.session() as s:
        o=s.get(PaidOperation,operation_id)
        if not o or o.project_id!=pid:raise LookupError('Операция не найдена')
        if body.action!='refresh' and o.status!='uncertain':
            raise ValueError('Ручная сверка доступна только для операций с неизвестным результатом. Дождитесь завершения активного запроса.')
        external_id=o.external_id
        org=s.get(Organization,cu.org_id)
        secrets=keys.all_secrets(s,org.id)
        legacy=(org.settings or {}).get("api_key") or config.POLZA_API_KEY
        if legacy and legacy not in secrets:secrets.append(legacy)
    if body.action=='refresh':
        if not external_id:raise ValueError('Нет номера задачи. Сверьте расход в кабинете провайдера вручную.')
        from ...ai import polza
        data=None;last=None
        for key in secrets:
            try:data=polza.get_task(key,external_id);break
            except Exception as e:last=e
        if data is None:raise ValueError('Не удалось проверить задачу Polza') from last
        if data.get('status') not in ('completed','failed','cancelled'):raise ValueError('Задача ещё выполняется')
        cost=polza.cost_of(data)
        if data.get('status')!='completed' and not cost:payments.release(operation_id,known=True)
        else:payments.settle(operation_id,cost,provider=data.get('provider',''))
    else:
        if len(body.note.strip())<5:raise ValueError('Укажите результат ручной сверки с провайдером')
        if body.action=='settle':payments.settle(operation_id,body.cost)
        else:payments.release(operation_id,known=True)
    with db.session() as s:
        o=s.get(PaidOperation,operation_id,with_for_update=True)
        o.note=(o.note+'\n' if o.note else '')+f'{cu.email}: {body.action}: {body.note.strip()}'
    return {'ok':True}
