"""Public CC0 geometry search/import from the fixed Poly Haven API."""
import asyncio
import json
import re
import struct
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter,HTTPException,Query
from pydantic import BaseModel,Field
from starlette.concurrency import run_in_threadpool

from .external_3d import mesh_result
from .generated_models import save_model
from .research import plain

router=APIRouter(prefix='/api/public-models',tags=['public-models'])
API='https://api.polyhaven.com'
ASSET_ID=r'[A-Za-z0-9_-]{1,100}'
MAX_DOWNLOAD=24*1024*1024
HEADERS={'User-Agent':'AIPaperModelar/0.1 (Poly Haven public 3D asset browser)'}
ALIASES={'椅子':'chair','いす':'chair','机':'table','テーブル':'table','家具':'furniture','建物':'building','家':'house','石':'rock','岩':'rock','木':'tree','植物':'plant','花':'flower','瓶':'bottle','ボトル':'bottle','ソファ':'sofa','車':'car','船':'boat','食器':'tableware','箱':'box','樽':'barrel','ベンチ':'bench','ランプ':'lamp','パン':'bread','果物':'fruit','りんご':'apple'}


async def fetch(c,url,limit=MAX_DOWNLOAD,params=None):
    data=bytearray()
    async with c.stream('GET',url,params=params) as response:
        response.raise_for_status()
        async for block in response.aiter_bytes():
            data.extend(block)
            if len(data)>limit:raise ValueError('Download too large')
    return bytes(data)


def asset_url(value):
    if not isinstance(value,str):raise ValueError('Invalid file URL')
    p=urlsplit(value)
    if p.scheme!='https' or p.hostname!='dl.polyhaven.org' or p.port not in {None,443} or p.username or p.password or p.query or p.fragment or not p.path.startswith('/file/ph-assets/Models/'):
        raise ValueError('Unapproved asset URL')
    if '..' in p.path.split('/'):raise ValueError('Invalid asset path')
    return value


def info(asset_id,item):
    authors=item.get('authors',{})
    return {'id':asset_id,'name':plain(item.get('name') or asset_id,120),
            'author':plain(', '.join(authors) if isinstance(authors,dict) else '',200),
            'license':'CC0','license_url':'https://polyhaven.com/license',
            'source_url':'https://polyhaven.com/a/'+asset_id,'provider':'Poly Haven',
            'polycount':item.get('polycount') if isinstance(item.get('polycount'),int) else None}


async def catalogue(c):
    data=json.loads(await fetch(c,API+'/assets',limit=4*1024*1024,params={'t':'models'}))
    if not isinstance(data,dict):raise ValueError('Invalid catalogue')
    return {key:item for key,item in data.items() if re.fullmatch(ASSET_ID,key) and isinstance(item,dict) and item.get('type',2)==2}


@router.get('')
async def search(q:str=Query(default='',max_length=120),offset:int=Query(default=0,ge=0,le=5000)):
    try:
        async with asyncio.timeout(20),httpx.AsyncClient(timeout=15,headers=HEADERS,follow_redirects=False,trust_env=False) as c:
            assets=await catalogue(c)
        query=ALIASES.get(q.strip(),q.strip()).casefold();terms=query.replace("_"," ").split()
        matches=[]
        for key,item in assets.items():
            tags=item.get('tags',[]);categories=item.get('categories',[])
            hay=' '.join([key,str(item.get('name','')),str(item.get('description','')),str(tags),str(categories)]).casefold()
            words=set(re.findall(r'[a-z0-9]+',hay))
            if all((term in words or term+'s' in words) if re.fullmatch(r'[a-z0-9]+',term) else term in hay for term in terms):matches.append(info(key,item))
        matches.sort(key=lambda m:(-sum(t in set(re.findall(r'[a-z0-9]+',m['name'].casefold())) for t in terms),m['name'].casefold()))
        return {'models':matches[offset:offset+12],'total':len(matches),'offset':offset,'next_offset':offset+12 if offset+12<len(matches) else None,'query':q,'search_terms':query,'provider':'Poly Haven'}
    except (httpx.HTTPError,ValueError,TypeError,AttributeError,TimeoutError):
        raise HTTPException(503,'公開3Dモデルを検索できません。時間をおいて再試行してください。') from None


def pack_geometry(tree,buffers):
    if not isinstance(tree,dict) or not isinstance(tree.get('buffers'),list) or len(tree['buffers'])!=len(buffers):raise ValueError('Invalid glTF')
    offsets=[];binary=bytearray()
    for spec,data in zip(tree['buffers'],buffers):
        if not isinstance(spec.get('byteLength'),int) or not 0<spec['byteLength']<=len(data):raise ValueError('Invalid buffer length')
        offsets.append(len(binary));binary.extend(data);binary.extend(b'\0'*((-len(binary))%4))
    for view in tree.get('bufferViews',[]):
        index=view.get('buffer',0)
        if not isinstance(index,int) or not 0<=index<len(offsets):raise ValueError('Invalid buffer index')
        offset=view.get('byteOffset',0);length=view.get('byteLength',0)
        if not isinstance(offset,int) or not isinstance(length,int) or offset<0 or length<0 or offset+length>len(buffers[index]):raise ValueError('Invalid buffer view')
        view['byteOffset']=offset+offsets[index];view['buffer']=0
    tree['buffers']=[{'byteLength':len(binary)}]
    for key in ('images','textures','materials'):tree.pop(key,None)
    for mesh in tree.get('meshes',[]):
        for primitive in mesh.get('primitives',[]):primitive.pop('material',None)
    raw=json.dumps(tree,separators=(',',':')).encode();raw+=b' '*((-len(raw))%4)
    return struct.pack('<4sIIII',b'glTF',2,28+len(raw)+len(binary),len(raw),0x4e4f534a)+raw+struct.pack('<II',len(binary),0x004e4942)+binary


async def geometry(c,asset_id):
    files=json.loads(await fetch(c,API+'/files/'+asset_id,limit=4*1024*1024))
    options=files.get('gltf',{})
    choice=options.get('1k') or options.get('2k') or options.get('4k') or next(iter(options.values()),{})
    spec=choice.get('gltf',{})
    tree=json.loads(await fetch(c,asset_url(spec.get('url')),limit=4*1024*1024))
    includes=spec.get('include',{});buffers=[];used=0
    entries=tree.get('buffers',[])
    if not isinstance(entries,list) or not 1<=len(entries)<=8:raise ValueError('Unsupported glTF buffers')
    for entry in entries:
        uri=entry.get('uri')
        if not isinstance(uri,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+\.bin',uri) or uri not in includes:raise ValueError('Unapproved buffer reference')
        part=await fetch(c,asset_url(includes[uri].get('url')),limit=MAX_DOWNLOAD-used)
        used+=len(part);buffers.append(part)
    return pack_geometry(tree,buffers)


class ImportRequest(BaseModel):
    asset_id:str=Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    height_mm:float=Field(default=120,ge=20,le=300,allow_inf_nan=False)
    consent:bool=False


@router.post('/import')
async def import_model(req:ImportRequest):
    if not req.consent:raise HTTPException(400,'出典と利用条件を確認して取得・保存に同意してください。')
    try:
        async with asyncio.timeout(90),httpx.AsyncClient(timeout=20,headers=HEADERS,follow_redirects=False,trust_env=False) as c:
            assets=await catalogue(c)
            if req.asset_id not in assets:raise HTTPException(404,'公開モデルが見つかりません。検索し直してください。')
            source=info(req.asset_id,assets[req.asset_id]);glb=await geometry(c,req.asset_id)
        result=await run_in_threadpool(mesh_result,glb,req.height_mm)
        result['obj']='# Source: '+source['source_url']+'\n# Author: '+source['author']+'\n# License: CC0 (Poly Haven)\n'+result['obj']
        attribution={key:source[key] for key in ('source_url','author','license','license_url')}
        saved=await run_in_threadpool(save_model,result,name=source['name'],provider='Poly Haven',glb=glb,attribution=attribution)
        return {**result,'name':source['name'],'provider':'Poly Haven','source':source,'saved_model':saved,
                'warnings':['Poly HavenのCC0公開モデルを取得しました。AIによる生成ではありません。',result['warnings'][1],'印刷用の高さへ調整しています。元の実物寸法・組立品質は未検証です。']}
    except (httpx.HTTPError,ValueError,TypeError,AttributeError,KeyError,IndexError,OverflowError,TimeoutError,OSError,RuntimeError):
        raise HTTPException(502,'公開モデルを取得・変換できません。容量やモデル形式の制限により対応できない場合があります。別のモデルを選んでください。') from None
