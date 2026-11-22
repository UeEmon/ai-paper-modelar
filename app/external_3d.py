"""Fixed-host image-to-mesh APIs. Keys, source images and meshes are request-only."""
import asyncio
import base64
import io
import json
import re
import struct
import uuid
from urllib.parse import urlsplit, quote

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

router=APIRouter(prefix='/api/3d',tags=['3d-providers'])
MODELS={
 'huggingface':['TRELLIS.2'],
 'meshy':['meshy-t2.5','meshy-t2','meshy-7.1','meshy-6','meshy-6-lite'],
 'tripo':['P1-20260311','P2-20260801','v3.1-20260211','v3.0-20250812','v2.5-20250123'],
}
HF='https://microsoft-trellis-2.hf.space'
MESHY='https://api.meshy.ai/openapi/v1'
TRIPO='https://openapi.tripo3d.ai/v3'
LIMIT=24*1024*1024


def credentials(request):
    provider=request.headers.get('x-3d-provider','')
    model=request.headers.get('x-3d-model','')
    key=request.headers.get('x-3d-key','')
    if provider not in MODELS or model not in MODELS[provider] or not re.fullmatch(r'[!-~]{0,512}',key) or (provider!='huggingface' and not key):
        raise HTTPException(400,'3D生成APIのモデルとキーを確認してください。')
    return provider,model,key


def auth(key):return {'Authorization':'Bearer '+key} if key else {}


def payload(response, tripo=False):
    response.raise_for_status();data=response.json()
    if tripo:
        if data.get('code')!=0:raise ValueError('API failure')
        data=data['data']
    if not isinstance(data,dict):raise ValueError('Invalid API response')
    return data


def task_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,160}',value):raise ValueError('Task ID')
    return value


@router.get('/models')
def models():
    return {'providers':MODELS}


@router.post('/test')
async def test(request:Request):
    provider,model,key=credentials(request)
    try:
        async with httpx.AsyncClient(timeout=20,follow_redirects=False,trust_env=False) as c:
            url=MESHY+'/balance' if provider=='meshy' else TRIPO+'/account/balance' if provider=='tripo' else 'https://huggingface.co/api/whoami-v2' if key else HF+'/gradio_api/info'
            data=payload(await c.get(url,headers=auth(key)),tripo=provider=='tripo')
            if provider=='huggingface' and not key and not {'/image_to_3d','/extract_glb'}.issubset(data.get('named_endpoints',{})):raise ValueError('API unavailable')
        return {'ok':True,'message':'接続を確認しました。生成は実行していません。モデルの生成権限・残高は生成時に確認されます。'}
    except (httpx.HTTPError,ValueError,KeyError,TypeError):
        raise HTTPException(502,'3D APIに接続できません。キー・利用権限・サービスの稼働状況を確認してください。') from None


async def download(c,url,provider):
    parts=urlsplit(url)
    hosts={'meshy':{'assets.meshy.ai'},'tripo':{'cdn.tripo3d.ai','tripo-data.rg1.data.tripo3d.com','tripo-data.cdn.bcebos.com'},'huggingface':{'microsoft-trellis-2.hf.space'}}
    if parts.scheme!='https' or parts.hostname not in hosts[provider] or parts.username or parts.password or parts.port not in {None,443}:
        raise ValueError('Unapproved output host')
    async with c.stream('GET',url) as response:
        response.raise_for_status();data=bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data)>LIMIT:raise ValueError('Model too large')
    return bytes(data)


async def poll(c,url,key,tripo=False):
    for _ in range(240):
        data=payload(await c.get(url,headers=auth(key)),tripo)
        status=str(data.get('status','')).lower()
        if status in {'succeeded','success'}:return data
        if status in {'failed','cancelled','canceled','expired','banned'}:raise ValueError('Generation failed')
        await asyncio.sleep(2)
    raise TimeoutError('Generation timed out')


async def hf_call(c,config,session,name,data,key):
    deps=[d for d in config['dependencies'] if d.get('api_name')==name]
    if len(deps)!=1:raise ValueError('Changed Space schema')
    joined=payload(await c.post(HF+'/gradio_api/queue/join',headers=auth(key),json={'data':data,'fn_index':deps[0]['id'],'session_hash':session}))
    event=joined.get('event_id')
    async with c.stream('GET',HF+'/gradio_api/queue/data',headers=auth(key),params={'session_hash':session}) as response:
        response.raise_for_status();total=0
        async for line in response.aiter_lines():
            total+=len(line)
            if total>2*1024*1024:raise ValueError('Oversized queue response')
            if not line.startswith('data:'):continue
            message=json.loads(line[5:])
            if message.get('event_id')!=event:continue
            if message.get('msg')=='process_completed':
                if message.get('success') is not True:
                    error=str(message.get('output',{}).get('error','')).lower()
                    if 'quota' in error:
                        raise HTTPException(429,'Hugging Faceの無料GPU枠が不足しています。HFトークンを設定するか、枠の回復を待ってください。有料サービスへの自動切替は行いません。')
                    raise ValueError('Space generation failed')
                return message['output']['data']
            if message.get('msg') in {'queue_full','unexpected_error'}:raise ValueError('Space queue failed')
    raise ValueError('Space stream ended')


async def generate(c,provider,model,key,jpeg):
    headers=auth(key)
    if provider=='meshy':
        body={'image_url':'data:image/jpeg;base64,'+base64.b64encode(jpeg).decode(),'ai_model':model,'target_polycount':300,'topology':'triangle','should_texture':False,'target_formats':['glb']}
        if model.startswith('meshy-t'):body['model_type']='smart-topology'
        else:body['should_remesh']=True
        created=payload(await c.post(MESHY+'/image-to-3d',headers=headers,json=body))
        tid=task_id(created['result'])
        result=await poll(c,MESHY+'/image-to-3d/'+tid,key)
        return await download(c,result['model_urls']['glb'],provider)
    if provider=='tripo':
        uploaded=payload(await c.post(TRIPO+'/files',headers=headers,files={'file':('reference.jpg',jpeg,'image/jpeg')}),True)
        created=payload(await c.post(TRIPO+'/generation/image-to-model',headers=headers,json={'input':uploaded['file_token'],'model':model,'face_limit':300,'texture':False,'pbr':False}),True)
        tid=task_id(created['task_id'])
        result=await poll(c,TRIPO+'/tasks/'+tid,key,True)
        return await download(c,result['output']['model_url'],provider)
    # Gradio state is tied to the same session across preprocessing, inference and export.
    config=payload(await c.get(HF+'/config',headers=headers));session=uuid.uuid4().hex
    uploaded=await c.post(HF+'/gradio_api/upload',headers=headers,files={'files':('reference.jpg',jpeg,'image/jpeg')})
    uploaded.raise_for_status();path=uploaded.json()[0]
    if not isinstance(path,str) or not path.startswith('/tmp/'):raise ValueError('Upload path')
    file={'path':path,'meta':{'_type':'gradio.FileData'},'orig_name':'reference.jpg'}
    await hf_call(c,config,session,'start_session',[],key)
    try:
        prepared=await hf_call(c,config,session,'preprocess_image',[file],key)
        image=prepared[0]
        await hf_call(c,config,session,'image_to_3d',[image,0,'512',7.5,.7,12,5.,7.5,.5,12,3.,1.,0.,12,3.],key)
        result=await hf_call(c,config,session,'extract_glb',[None,300,512],key)
        value=next(v for v in result if isinstance(v,dict) and isinstance(v.get('path'),str))
        # Ignore an upstream URL: construct the fixed Space file endpoint ourselves.
        if not value['path'].startswith('/tmp/'):raise ValueError('Output path')
        return await download(c,HF+'/gradio_api/file='+quote(value['path'],safe='/'),provider)
    finally:
        # Best effort removal of the remote session's generated intermediates.
        try:await hf_call(c,config,session,'end_session',[],key)
        except (httpx.HTTPError,ValueError,KeyError,TypeError,HTTPException):pass


def mesh_result(data,height):
    """Read self-contained geometry only; never resolve URLs or material files."""
    import numpy as np
    import trimesh
    from .mesh_unfolder import load_mesh
    if len(data)<20 or data[:4]!=b'glTF':raise ValueError('Expected GLB')
    version,length,chunk_size,kind=struct.unpack_from('<IIII',data,4)
    if version!=2 or length!=len(data) or kind!=0x4e4f534a or chunk_size>4*1024*1024:raise ValueError('GLB header')
    tree=json.loads(data[20:20+chunk_size])
    if any('uri' in b for b in tree.get('buffers',[])):raise ValueError('External buffers')
    if sum(a.get('count',0) for a in tree.get('accessors',[]))>2_000_000:raise ValueError('Too many elements')
    for key in ('images','textures','materials'):tree.pop(key,None)
    for m in tree.get('meshes',[]):
        for p in m.get('primitives',[]):p.pop('material',None)
    raw=json.dumps(tree,separators=(',',':')).encode();raw+=b' '*((-len(raw))%4)
    rest=data[20+chunk_size:]
    clean=struct.pack('<4sIIII',b'glTF',2,20+len(raw)+len(rest),len(raw),0x4e4f534a)+raw+rest
    scene=trimesh.load_scene(io.BytesIO(clean),file_type='glb',process=False,skip_materials=True)
    mesh=scene.to_mesh()
    if (not len(mesh.faces) or len(mesh.faces)>500_000 or not np.isfinite(mesh.vertices).all()
            or mesh.faces.min()<0 or mesh.faces.max()>=len(mesh.vertices)):raise ValueError('Mesh size')
    before=len(mesh.faces)
    if before>400:mesh=mesh.simplify_quadric_decimation(face_count=400)
    bounds=mesh.bounds; extent=bounds[1]-bounds[0]
    if min(extent)<=1e-10:raise ValueError('Flat model')
    mesh.vertices=(mesh.vertices-(bounds[0]+[extent[0]/2,0,extent[2]/2]))*(height/extent[1])
    obj=trimesh.exchange.obj.export_obj(mesh,include_color=False,include_texture=False,include_normals=False)
    checked=load_mesh(obj.encode(),'generated.obj')
    return {'vertices':checked.vertices,'faces':checked.faces,'obj':obj,'colors':['#c9b38b']*len(checked.faces),
            'size_mm':np.round(mesh.extents,2).tolist(),'components':[], 'notes':[],
            'warnings':['外部AIが画像から推定した3Dです。裏面・寸法・組立品質は未検証です。',f'展開用に{before}面から{len(checked.faces)}面へ調整しました。形状の細部やテクスチャは再現されません。'],'estimated':True}


class GenerateRequest(BaseModel):
    image_id:str=Field(pattern=r'^[0-9a-f]{32}$')
    name:str=Field(default='外部AI模型',min_length=1,max_length=80)
    height_mm:float=Field(default=120,ge=20,le=300,allow_inf_nan=False)
    consent:bool=False
    cost_consent:bool=False


@router.post('/generate')
async def create(req:GenerateRequest,request:Request):
    provider,model,key=credentials(request)
    if not req.consent or not req.cost_consent:raise HTTPException(400,'画像の外部送信と利用条件・料金を確認してください。')
    from .image_models import choice,preview
    item=choice(req.image_id)
    try:
        jpeg=await preview(item)
        async with asyncio.timeout(600),httpx.AsyncClient(timeout=120,follow_redirects=False,trust_env=False) as c:
            data=await generate(c,provider,model,key,jpeg)
        result=await run_in_threadpool(mesh_result,data,req.height_mm)
        return {**result,'name':req.name,'provider':provider,'source':item.metadata}
    except (httpx.HTTPError,ValueError,KeyError,TypeError,IndexError,TimeoutError,RuntimeError,OSError):
        raise HTTPException(502,'3D生成に失敗しました。利用枠・残高・モデル対応・稼働状況を確認してください。課金済みの可能性があるため、提供元の履歴を確認してから再実行してください。') from None
