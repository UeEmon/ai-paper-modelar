"""Persistent generated geometry library; input references and credentials are excluded."""
from datetime import datetime, timezone
import json
import os
import re
import shutil
import threading
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from .mesh_unfolder import load_mesh
from .retention import root

router=APIRouter(prefix='/api/generated-models',tags=['generated-models'])
_lock=threading.RLock()
ID=r'[a-f0-9]{32}'


def _folder(model_id):
    if not re.fullmatch(ID,model_id):raise HTTPException(404,'生成モデルが見つかりません。')
    path=root()/'models'/model_id
    if path.is_symlink() or not path.is_dir():raise HTTPException(404,'生成モデルが見つかりません。')
    return path


def _metadata(folder):
    path=folder/'metadata.json'
    if path.is_symlink() or path.stat().st_size>128*1024:raise ValueError('Invalid metadata')
    data=json.loads(path.read_text())
    if data.get('id')!=folder.name or not isinstance(data.get('name'),str):raise ValueError('Invalid model metadata')
    return data


def _public(meta):
    base='/api/generated-models/'+meta['id']
    return {key:meta[key] for key in ('id','name','provider','created_at','size_mm','faces')} | {
        'preview_url':base,'obj_url':base+'/model.obj',
        'glb_url':base+'/original.glb' if meta.get('has_glb') else None,
    }


def save_model(result,*,name,provider,glb=None):
    """Only validated generated OBJ, optional provider GLB and geometry metadata."""
    obj=result['obj'].encode()
    mesh=load_mesh(obj,'generated.obj')
    model_id=uuid.uuid4().hex
    colors=result.get('colors',[])
    if len(colors)!=len(mesh.faces) or any(not isinstance(c,str) or not re.fullmatch(r'#[a-fA-F0-9]{6}',c) for c in colors):
        colors=['#c9b38b']*len(mesh.faces)
    # No source object, image, prompt, notes or credentials are copied from result.
    meta={'id':model_id,'name':str(name)[:80],'provider':provider,
          'created_at':datetime.now(timezone.utc).isoformat(),
          'size_mm':result['size_mm'],'faces':len(mesh.faces),'colors':colors,'has_glb':glb is not None}
    folder=root()/'models';folder.mkdir(parents=True,exist_ok=True)
    staging=folder/('.partial-'+model_id)
    with _lock:
        try:
            staging.mkdir()
            (staging/'model.obj').write_bytes(obj)
            if glb is not None:(staging/'original.glb').write_bytes(glb)
            (staging/'metadata.json').write_text(json.dumps(meta,ensure_ascii=False),encoding='utf-8')
            os.replace(staging,folder/model_id)
        except OSError:
            shutil.rmtree(staging,ignore_errors=True)
            raise HTTPException(507,'3Dモデルのサーバー保存に失敗しました。空き容量と保存先の権限を確認してください。') from None
    return _public(meta)


@router.get('')
def index():
    folder=root()/'models';models=[]
    with _lock:
        for path in folder.iterdir() if folder.exists() else []:
            if not re.fullmatch(ID,path.name) or path.is_symlink() or not path.is_dir():continue
            try:models.append(_public(_metadata(path)))
            except (OSError,ValueError,KeyError,TypeError):continue
    return {'models':sorted(models,key=lambda m:m['created_at'],reverse=True)}


@router.get('/{model_id}')
def show(model_id:str):
    with _lock:
        folder=_folder(model_id)
        try:
            meta=_metadata(folder);path=folder/'model.obj'
            if path.is_symlink() or path.stat().st_size>5*1024*1024:raise ValueError('Invalid OBJ')
            obj=path.read_text();mesh=load_mesh(obj.encode(),'generated.obj')
        except (OSError,ValueError,KeyError,TypeError):
            raise HTTPException(404,'保存された生成モデルを読み込めません。') from None
    return {'name':meta['name'],'provider':meta['provider'],'obj':obj,'vertices':mesh.vertices,
            'faces':mesh.faces,'size_mm':meta['size_mm'],'colors':meta.get('colors',[]),
            'components':[],'notes':[],'warnings':['保存済みのAI生成モデルです。寸法・裏面・組立品質は未検証です。'],
            'estimated':True,'saved_model':_public(meta)}


@router.get('/{model_id}/{filename}')
def download(model_id:str,filename:str):
    if filename not in {'model.obj','original.glb'}:raise HTTPException(404,'生成モデルが見つかりません。')
    path=_folder(model_id)/filename
    if not path.is_file() or path.is_symlink():raise HTTPException(404,'生成モデルが見つかりません。')
    return FileResponse(path,media_type='model/gltf-binary' if filename.endswith('.glb') else 'application/octet-stream',filename='generated-'+filename,headers={'Cache-Control':'no-store'})


@router.delete('/{model_id}',status_code=204)
def delete(model_id:str):
    with _lock:shutil.rmtree(_folder(model_id))
