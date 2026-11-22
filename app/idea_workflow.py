"""Genre/keyword discovery for drawing -> 3D and existing public-model paths."""
import asyncio
from typing import Literal
from fastapi import APIRouter,Query
from .generator import SubjectType
from .image_models import search_images
from .public_models import search as public_search

router=APIRouter(prefix='/api/idea',tags=['idea-workflow'])
DRAWING_TERMS={
 'architecture':'plan OR elevation OR blueprint',
 'vehicle':'diagram OR blueprint OR drawing',
 'landscape':'map OR topographic OR diagram',
 'prop':'diagram OR drawing OR plan',
 'character':'drawing OR turnaround OR model sheet',
 'original':'drawing OR diagram',
 'railway':'diagram OR plan OR blueprint',
 'other':'drawing OR diagram',
}


@router.get('/references')
async def discover(word:str=Query(min_length=1,max_length=120),genre:SubjectType='architecture',kind:Literal['both','diagram','photo']='both'):
    tasks=[];names=[]
    if kind in {'both','diagram'}:
        names.append('diagrams');tasks.append(search_images(word+' ('+DRAWING_TERMS[genre]+')'))
    if kind in {'both','photo'}:
        names.append('photos');tasks.append(search_images(word))
    names.append('public_models');tasks.append(public_search(word,0))
    values=await asyncio.gather(*tasks,return_exceptions=True)
    result={'diagrams':[],'photos':[],'public_models':[],'warnings':[], 'word':word,'genre':genre}
    labels={'diagrams':'構造図候補','photos':'参考画像','public_models':'公開3Dモデル'}
    for name,value in zip(names,values):
        if isinstance(value,BaseException):
            result['warnings'].append(labels[name]+'を検索できませんでした。他の結果を利用するか再検索してください。')
            continue
        if name=='public_models':result[name]=value['models'][:6]
        else:
            result[name]=[{**image,'reference_type':'diagram' if name=='diagrams' else 'photo'} for image in value[:6]]
    result['note']='構造図候補は検索語による分類です。実際の内容・利用条件・寸法は出典で確認してください。検索だけではAI送信や3Dモデル本体の取得は行いません。'
    return result
