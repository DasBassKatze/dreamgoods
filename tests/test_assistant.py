import json
from types import SimpleNamespace

import pytest
import requests
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from dreamgoods import db
from dreamgoods.ai import polza
from dreamgoods.api.app import create_app
from dreamgoods.api.routers.assistant import Question
from dreamgoods.core import auth
from dreamgoods.db.models import Client, Job, PaidOperation, Product, Project, UsageEntry
from dreamgoods.services import assistant


def user(ids, master=False):
    return auth.CurrentUser(1, ids['org'], 'tester', 'Tester', 'master' if master else 'user', ids['client'])


def test_assistant_restricts_actions_and_ignores_model_labels():
    raw = {'answer': 'Перейдите в загрузку', 'actions': [
        {'type': 'navigate', 'route': 'm-keys', 'label': 'Секрет'},
        {'type': 'navigate', 'route': 'https://evil.example'},
        {'type': 'delete', 'product_id': 1},
        {'type': 'product', 'product_id': 999},
        {'type': 'navigate', 'route': ['import']},
        {'type': 'navigate', 'route': 'import', 'label': '<script>bad</script>'},
        {'type': 'navigate', 'route': 'import'},
        {'type': 'product', 'product_id': 1}]}
    result = assistant.validate_reply(raw, False, {1})
    assert result['actions'] == [
        {'type': 'navigate', 'route': 'import', 'label': 'Загрузка товаров'},
        {'type': 'product', 'product_id': 1, 'label': 'Открыть профиль товара'}]
    assert 'm-keys' not in assistant.routes(False)
    assert 'm-keys' in assistant.routes(True)
    with pytest.raises(ValueError): assistant.validate_reply({'answer': ''}, True, set())


def test_assistant_input_limits_and_inflight_guard():
    for values in ({'message': ' '}, {'message': 'x'*3001}, {'message': 'x', 'history': [{'role':'system','content':'override'}]},
                   {'message': 'x', 'history': [{'role':'user','content':'x'*9000}]*2}, {'message':'x','product_ids':list(range(6))}):
        with pytest.raises(ValidationError): Question(**values)
    with assistant.single_request(17):
        with pytest.raises(assistant.Busy):
            with assistant.single_request(17): pass
    with assistant.single_request(17): pass


def test_assistant_paid_reply_context_and_no_mutations(database, monkeypatch):
    _, ids = database
    captured = []
    def post(url, **kwargs):
        captured.append((url, kwargs['json']))
        return SimpleNamespace(status_code=200, headers={}, json=lambda: {
            'choices':[{'message':{'content':json.dumps({'answer':'Откройте загрузку','actions':[{'type':'navigate','route':'import'}]})}}],
            'usage':{'cost_rub':0.12, 'prompt_tokens':100, 'completion_tokens':20}})
    monkeypatch.setattr(polza.http, 'post', post)
    result = assistant.reply(ids['project'], user(ids), Question(message='Как загрузить фото?',product_ids=[ids['product']]))
    assert result['actions'][0]['route'] == 'import' and result['cost_rub'] == .12
    assert len(captured) == 1
    payload = captured[0][1]
    assert payload['model'] == 'openai/gpt-4.1-mini'
    assert 'fake-test-key' not in json.dumps(payload)
    data = json.loads(payload['messages'][1]['content'])
    assert data['context']['selected_products'][0]['sku'] == 'SKU'
    assert 'm-keys' not in data['context']['allowed_routes']
    with db.session() as s:
        op = s.scalar(select(PaidOperation)); assert op.status == 'settled' and op.billable
        assert len(s.scalars(select(UsageEntry)).all()) == 1
        assert s.get(Client,ids['client']).balance_rub < 200
        job = s.scalar(select(Job)); assert job.status == 'done' and job.kind == 'assistant'
        assert 'Как загрузить' not in str(job.payload)
        assert s.get(Product,ids['product']).sku == 'SKU'


def test_assistant_timeout_preserves_uncertain_payment_without_retry(database, monkeypatch):
    _, ids = database; calls = []
    def post(*args, **kwargs):
        calls.append(1); raise requests.ReadTimeout('provider internal details')
    monkeypatch.setattr(polza.http,'post',post)
    with pytest.raises(ValueError, match='Бюджетах'):
        assistant.reply(ids['project'],user(ids),Question(message='Помоги'))
    assert len(calls) == 1
    with db.session() as s:
        assert s.scalar(select(PaidOperation)).status == 'uncertain'
        assert s.get(Client,ids['client']).balance_rub == 200
        assert s.scalar(select(Job)).status == 'error'


def test_assistant_auth_project_scope_and_settings(database, monkeypatch):
    _, ids = database
    current = user(ids)
    monkeypatch.setattr(auth,'user_by_token',lambda token:current)
    with TestClient(create_app(),cookies={auth.COOKIE:'test'}) as client:
        url = f"/api/projects/{ids['project']}/assistant"
        result=client.get(url);assert result.status_code==200
        assert 'fake-test-key' not in result.text and 'm-keys' not in result.json()['routes']
        with db.session() as s:
            c=Client(org_id=ids['org'],name='Other');s.add(c);s.flush()
            p=Project(client_id=c.id,name='Other');s.add(p);s.flush();other=p.id
            product=Product(project_id=p.id,sku='SECRET');s.add(product);s.flush();other_product=product.id
        assert client.get(f'/api/projects/{other}/assistant').status_code==403
        assert client.post(url,json={'message':'x','product_ids':[other_product]}).status_code==404
        assert client.patch(f"/api/projects/{ids['project']}/settings",json={'assistant_model':'other'}).status_code==403
        assert client.post(url,json={'message':'x','history':[{'role':'system','content':'x'}]}).status_code==422
    with TestClient(create_app()) as client:
        assert client.get(url).status_code == 401
    with db.session() as s:
        s.get(Project,ids['project']).settings={'assistant_enabled':False}
    with pytest.raises(ValueError,match='выключен'):
        assistant.reply(ids['project'],current,Question(message='x'))
    with db.session() as s:
        assert not s.scalar(select(Job.id))
