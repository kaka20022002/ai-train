"""VR bridge contract: preparation-only, isolated data, revocation and retries."""
import time
import secrets

import pytest

from models import TrainingProgram, TrainingSession
from routers.auth import issue_token
from vr_bridge.api import _attempts
from vr_bridge.models import VRConnection, VRResult, VRPairing


@pytest.fixture(autouse=True)
def clear_limiter():
    _attempts.clear()
    yield
    _attempts.clear()


def user(client, uid="vr_test"):
    response = client.post("/users", json={
        "user_id": uid, "basic_info": {"age": 28, "gender": "unknown"},
        "fitness_level": "beginner", "medical_history": [],
    })
    assert response.status_code == 201
    return {"Authorization": f"Bearer {issue_token(uid)}"}


def pairing(client, web):
    response=client.post('/vr/pairings',headers=web,json={})
    assert response.status_code==201
    data=response.json()
    body={'code':data['code'],'device_name':'测试头显','device_secret':secrets.token_urlsafe(32)}
    reply=client.post('/vr/device/pairings/redeem',json=body)
    assert reply.status_code==200
    data.update(reply.json())
    return data, {'Authorization':'Bearer '+data['device_token']}

def linked(client):
    web=user(client)
    data,device=pairing(client,web)
    return web,device,data

def result_payload():
    return {"client_session_id": "vr-real-session-1", "context_user_id": "vr_test", "started_at": "2026-10-28T10:00:00+08:00",
            "ended_at": "2026-10-28T10:10:00+08:00", "outcome": "completed",
            "actions": [{"action_id": "squat_air_fbx_parsed", "action_name": "自重深蹲",
                         "completed_sets": 2, "completed_reps": 12, "quality_score_01": .8}]}


def test_short_code_is_single_use_and_secret_not_exposed(client, db_session):
    web=user(client)
    assert client.post('/vr/pairings',json={}).status_code==401
    data=client.post('/vr/pairings',headers=web,json={}).json()
    assert len(data['code'])==6 and data['code'].isascii() and data['code'].isdigit()
    assert 'device_token' not in data
    stored=db_session.query(VRPairing).one()
    assert stored.code_hash != data['code']
    body={'code':data['code'],'device_name':'测试头显','device_secret':secrets.token_urlsafe(32)}
    reply=client.post('/vr/device/pairings/redeem',json=body)
    assert reply.status_code==200 and reply.json()['user_id']=='vr_test'
    retry=client.post('/vr/device/pairings/redeem',json=body)
    assert retry.json()['device_token']==reply.json()['device_token']
    body['device_secret']=secrets.token_urlsafe(32)
    assert client.post('/vr/device/pairings/redeem',json=body).status_code==400
    overview=client.get('/vr/overview',headers=web).json()
    assert overview['pairing'] is None and reply.json()['device_token'] not in str(overview)
    assert db_session.query(VRConnection).count()==1

def test_expired_and_invalid_code_do_not_bind(client, db_session):
    web=user(client)
    data=client.post('/vr/pairings',headers=web,json={}).json()
    db_session.query(VRPairing).one().expires_at=int(time.time())-1
    db_session.commit()
    body={'code':data['code'],'device_name':'测试','device_secret':secrets.token_urlsafe(32)}
    assert client.post('/vr/device/pairings/redeem',json=body).status_code==400
    assert client.get('/vr/overview',headers=web).json()['pairing'] is None
    assert db_session.query(VRConnection).count()==0

def test_web_and_device_credentials_are_separate(client):
    web, device, _ = linked(client)
    assert client.get("/vr/overview").status_code == 401
    assert client.get("/vr/overview", headers=device).status_code == 401
    assert client.get("/vr/device/context", headers=web).status_code == 401
    assert client.get("/vr/device/context", headers={"Authorization": "Bearer bad.token"}).status_code == 401


def test_user_cannot_read_or_modify_other_users_connection(client):
    owner, device, _ = linked(client)
    other = user(client, "vr_other")
    assert client.get("/vr/overview", headers=other).json()["connection"] is None
    assert client.put("/vr/connection/reference", headers=other, json={"enabled": False}).status_code == 404
    assert client.delete("/vr/connection", headers=other).status_code == 404
    assert client.get("/vr/device/context", headers=device).json()["user_id"] == "vr_test"
    assert client.get("/vr/overview", headers=owner).json()["connection"] is not None


def test_optional_reference_does_not_restrict_vr_or_advance_program(client, db_session):
    web = user(client)
    program = TrainingProgram(program_id="program_vr", user_id="vr_test", name="网页计划",
                              goal="general_fitness", split_type="full_body", total_weeks=4,
                              current_week=1, sessions_per_week=3, status="active", program_data={
                                  "weeks": [{"week_number": 1, "sessions": [{
                                      "label": "今日网页训练", "workout_type": "full_body",
                                      "key_exercises": [{"name": "Barbell Squat", "sets": 3, "reps": "8"}],
                                  }]}]})
    db_session.add(program)
    db_session.commit()
    data, device = pairing(client,web)
    context = client.get("/vr/device/context", headers=device).json()
    assert context["today_reference"] is None
    assert context["vr_schedule_authoritative"] and context["training_channel"] == "none"
    assert client.put("/vr/connection/reference", headers=web, json={"enabled": True}).status_code == 200
    context = client.get("/vr/device/context", headers=device).json()
    assert context["today_reference"]["title"] == "今日网页训练"
    # Device trains a different movement/variant and amount; this is permitted.
    assert client.post("/vr/device/results", headers=device, json=result_payload()).status_code == 200
    assert db_session.query(TrainingSession).count() == 0
    db_session.refresh(program)
    assert program.current_week == 1
    assert len(program.program_data["weeks"][0]["sessions"]) == 1
    assert client.put("/vr/connection/reference", headers=web, json={"enabled": False}).status_code == 200
    assert client.get("/vr/device/context", headers=device).json()["today_reference"] is None


def test_missing_reference_never_prevents_unassisted_vr(client):
    web=user(client)
    assert client.post('/vr/pairings',headers=web,json={'include_today_plan':True}).status_code==409
    data,device=pairing(client,web)
    assert client.get('/vr/device/context',headers=device).json()['today_reference'] is None

def test_result_retry_is_idempotent_but_conflicting_retry_is_rejected(client, db_session):
    web, device, _ = linked(client)
    payload = result_payload()
    first = client.post("/vr/device/results", headers=device, json=payload).json()
    second = client.post("/vr/device/results", headers=device, json=payload).json()
    assert first["id"] == second["id"] and second["duplicate"] is True
    payload["actions"][0]["completed_reps"] = 99
    assert client.post("/vr/device/results", headers=device, json=payload).status_code == 409
    assert db_session.query(VRResult).count() == 1
    assert len(client.get("/vr/overview", headers=web).json()["results"]) == 1


def test_disconnect_revokes_device_but_keeps_history(client):
    web, device, _ = linked(client)
    assert client.post("/vr/device/results", headers=device, json=result_payload()).status_code == 200
    assert client.delete("/vr/connection", headers=web).status_code == 204
    assert client.get("/vr/device/context", headers=device).status_code == 410
    assert client.post("/vr/device/results", headers=device, json=result_payload()).status_code == 410
    overview = client.get("/vr/overview", headers=web).json()
    assert overview["connection"] is None and len(overview["results"]) == 1


def test_unpaired_device_cannot_upload(client):
    assert client.post('/vr/device/results',headers={'Authorization':'Bearer unknown.secret'},json=result_payload()).status_code==401

def test_old_users_offline_result_is_not_assigned_to_current_user(client, db_session):
    _, device, _ = linked(client)
    payload = result_payload()
    payload["context_user_id"] = "previous_headset_user"
    assert client.post("/vr/device/results", headers=device, json=payload).status_code == 409
    assert db_session.query(VRResult).count() == 0


def test_guessing_short_codes_is_rate_limited(client):
    for _ in range(6):
        assert client.post('/vr/device/pairings/redeem',json={'code':'000000','device_name':'测试','device_secret':secrets.token_urlsafe(32)}).status_code==400
    assert client.post('/vr/device/pairings/redeem',json={'code':'000000','device_name':'测试','device_secret':secrets.token_urlsafe(32)}).status_code==429

def test_existing_connection_is_not_silently_overwritten(client):
    web,device,_=linked(client)
    assert client.post('/vr/pairings',headers=web,json={}).status_code==409
    assert client.get('/vr/device/context',headers=device).json()['user_id']=='vr_test'

@pytest.mark.parametrize("change", ["score", "time", "timezone"])
def test_invalid_results_are_not_stored(client, db_session, change):
    _, device, _ = linked(client)
    payload = result_payload()
    if change == "score":
        payload["actions"][0]["quality_score_01"] = 2
    elif change == "time":
        payload["ended_at"] = "2026-10-27T10:10:00+08:00"
    else:
        payload["started_at"] = "2026-10-28T10:00:00"
    assert client.post("/vr/device/results", headers=device, json=payload).status_code == 422
    assert db_session.query(VRResult).count() == 0


def test_regeneration_cancel_and_other_user_isolation(client):
    web=user(client);other=user(client,'other')
    first=client.post('/vr/pairings',headers=web,json={}).json()
    second=client.post('/vr/pairings',headers=web,json={}).json()
    body={'code':first['code'],'device_name':'测试','device_secret':secrets.token_urlsafe(32)}
    assert client.post('/vr/device/pairings/redeem',json=body).status_code==400
    assert client.get('/vr/overview',headers=other).json()['pairing'] is None
    client.delete('/vr/pairings',headers=other)
    body['code']=second['code']
    assert client.post('/vr/device/pairings/redeem',json=body).status_code==200
    client.delete('/vr/connection',headers=web)
    third=client.post('/vr/pairings',headers=web,json={}).json()
    assert client.delete('/vr/pairings',headers=web).status_code==204
    body['code']=third['code'];body['device_secret']=secrets.token_urlsafe(32)
    assert client.post('/vr/device/pairings/redeem',json=body).status_code==400


def test_leading_zero_and_optional_reference_at_issuance(client, db_session, monkeypatch):
    web=user(client)
    db_session.add(TrainingProgram(program_id='ref',user_id='vr_test',name='参考',goal='general_fitness',split_type='full_body',total_weeks=4,current_week=1,sessions_per_week=3,status='active',program_data={'weeks':[{'week_number':1,'sessions':[{'label':'参考课表','key_exercises':[]}]}]}))
    db_session.commit()
    monkeypatch.setattr('vr_bridge.api.secrets.randbelow',lambda _:123)
    data=client.post('/vr/pairings',headers=web,json={'include_today_plan':True}).json()
    assert data['code']=='000123' and data['reference']['title']=='参考课表'
    reply=client.post('/vr/device/pairings/redeem',json={'code':data['code'],'device_name':'测试','device_secret':secrets.token_urlsafe(32)})
    assert reply.status_code==200 and reply.json()['today_reference']['title']=='参考课表'


def test_retired_pairing_direction_is_explicit(client):
    assert client.post('/vr/device/pairings',json={}).status_code==410
    assert client.post('/vr/connection',json={}).status_code==410


def test_regeneration_never_reuses_the_immediately_previous_code(client,monkeypatch):
    web=user(client)
    numbers=iter([42,42,43])
    monkeypatch.setattr('vr_bridge.api.secrets.randbelow',lambda _:next(numbers))
    first=client.post('/vr/pairings',headers=web,json={}).json()
    second=client.post('/vr/pairings',headers=web,json={}).json()
    assert first['code']=='000042' and second['code']=='000043'


def test_cancel_after_redemption_does_not_unlink_and_revoked_retry_cannot_resurrect(client):
    web=user(client)
    code=client.post('/vr/pairings',headers=web,json={}).json()['code']
    body={'code':code,'device_name':'测试','device_secret':secrets.token_urlsafe(32)}
    first=client.post('/vr/device/pairings/redeem',json=body).json()
    assert client.delete('/vr/pairings',headers=web).status_code==204
    assert client.get('/vr/device/context',headers={'Authorization':'Bearer '+first['device_token']}).status_code==200
    assert client.delete('/vr/connection',headers=web).status_code==204
    assert client.post('/vr/device/pairings/redeem',json=body).status_code==410


def test_previous_version_connected_device_keeps_its_credential(client,db_session):
    import hashlib
    web=user(client)
    secret=secrets.token_urlsafe(32)
    db_session.add(VRConnection(id='legacy-active-device',device_name='旧版已关联设备',secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
        code_hash=None,expires_at=int(time.time())-100,user_id='vr_test',state='connected',connected_at=int(time.time())-500))
    db_session.commit()
    device={'Authorization':'Bearer legacy-active-device.'+secret}
    assert client.get('/vr/device/context',headers=device).json()['user_id']=='vr_test'
    assert client.post('/vr/device/results',headers=device,json=result_payload()).status_code==200
    assert client.get('/vr/overview',headers=web).json()['connection']['device_name']=='旧版已关联设备'


@pytest.mark.parametrize('program_data', [None, 'old-format', {'weeks':None},
    {'weeks':[None,{'week_number':1,'sessions':None}]}, {'weeks':[{'week_number':1,'sessions':['old-format']}]}])
def test_malformed_legacy_plan_does_not_block_unassisted_pairing(client,db_session,program_data):
    web=user(client)
    db_session.add(TrainingProgram(program_id='old-format',user_id='vr_test',name='旧计划',goal='general_fitness',
        split_type='full_body',total_weeks=4,current_week=1,sessions_per_week=3,status='active',program_data=program_data))
    db_session.commit()
    reply=client.get('/vr/overview',headers=web)
    assert reply.status_code==200 and reply.json()['today_reference'] is None
    assert client.post('/vr/pairings',headers=web,json={}).status_code==201


def test_reference_preview_is_normalized_without_editing_original_plan(client,db_session):
    import copy
    web=user(client)
    data={'weeks':[{'week_number':1,'sessions':[{'label':'旧计划参考','estimated_duration_minutes':'unknown',
        'phases':{'main_lifts':None},'key_exercises':[None,{'name':'Squat','sets':3,'reps':8},
        {'name':'Broken','sets':'unknown','reps':[]}]}]}]}
    original=copy.deepcopy(data)
    program=TrainingProgram(program_id='legacy-preview',user_id='vr_test',name='旧计划',goal='general_fitness',
        split_type='full_body',total_weeks=4,current_week=1,sessions_per_week=3,status='active',program_data=data)
    db_session.add(program);db_session.commit()
    reference=client.get('/vr/overview',headers=web).json()['today_reference']
    assert reference['key_exercises']==[{'name':'Squat','sets':3,'reps':'8'}]
    assert reference['phases']=={'main_lifts':[]} and reference['estimated_duration_minutes'] is None
    db_session.refresh(program)
    assert program.program_data==original and program.current_week==1
