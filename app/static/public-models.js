"use strict";
(() => {
 const get=id=>document.getElementById(id),list=get('publicModelResults'),note=text=>{get('publicModelMessage').textContent=text;};
 let version=0,searchVersion=0,next=null,activeQuery='',importing=false;
 const add=(parent,tag,text)=>{const el=document.createElement(tag);el.textContent=text;parent.append(el);return el;};
 function enabled(){for(const button of list.querySelectorAll('button'))button.disabled=importing||!get('publicModelConsent').checked;}
 function invalidate(){version++;searchVersion++;get('publicModelSearch').disabled=false;get('publicModelMore').disabled=false;get('publicModelConsent').disabled=false;activeQuery='';next=null;list.replaceChildren();get('publicModelMore').hidden=true;get('publicModelConsent').checked=false;note('条件を変更しました。もう一度検索して利用条件を確認してください。');}
 get('publicModelQuery').addEventListener('input',invalidate);
 get('publicModelHeight').addEventListener('input',()=>{version++;get('publicModelConsent').checked=false;enabled();});
 get('publicModelConsent').addEventListener('change',()=>{version++;enabled();});
 async function search(offset=0){
  const query=get('publicModelQuery').value.trim(),request=++searchVersion;version++;
  get('publicModelSearch').disabled=true;get('publicModelMore').disabled=true;get('publicModelConsent').disabled=true;
  note('Poly Havenの公開3Dモデルを検索しています…');
  if(!offset){list.replaceChildren();get('publicModelConsent').checked=false;}
  try{
   const response=await fetch('/api/public-models?q='+encodeURIComponent(query)+'&offset='+offset,{cache:'no-store'}),data=await response.json();
   if(request!==searchVersion)return;if(!response.ok)throw Error(data.detail||'公開3Dを検索できませんでした。');
   activeQuery=query;next=data.next_offset;get('publicModelMore').hidden=next===null;
   for(const model of data.models){
    const row=add(list,'div','');row.className='savedGeneratedModel';add(row,'strong',model.name);
    add(row,'p','Poly Haven / '+(model.author||'作者は出典を確認')+' / '+model.license+(model.polycount?' / 元モデル約'+model.polycount+'面':''));
    const source=add(row,'a','出典・CC0利用条件を確認');source.href=model.source_url;source.target='_blank';source.rel='noopener noreferrer';
    const button=add(row,'button','取得・保存して3Dを開く');button.type='button';button.className='secondary';
    button.addEventListener('click',()=>retrieve(model));
   }
   enabled();note(data.total?data.total+'件見つかりました。モデル本体は取得ボタンを押すまでダウンロードしません。':'モデルが見つかりません。chair、table、rockなど英語の名前でも試してください。');
  }catch(e){if(request===searchVersion)note(e.message);}
  finally{if(request===searchVersion){get('publicModelSearch').disabled=false;get('publicModelMore').disabled=false;get('publicModelConsent').disabled=false;}}
 }
 async function retrieve(model){
  if(importing||!get('publicModelConsent').checked)return;
  const request=++version,height=Number(get('publicModelHeight').value);
  if(!Number.isFinite(height)||height<20||height>300){note('高さは20〜300mmで指定してください。');return;}
  importing=true;enabled();note('公開3Dモデルを取得し、プレビューと展開用の形状を保存しています…');
  try{
   const response=await fetch('/api/public-models/import',{method:'POST',headers:{'Content-Type':'application/json'},cache:'no-store',redirect:'error',body:JSON.stringify({asset_id:model.id,height_mm:height,consent:true})}),data=await response.json();
   if(!response.ok)throw Error(data.detail||'公開モデルを取得できませんでした。');
   window.dispatchEvent(new Event('paper-generated-model-saved'));
   if(request!==version){note('取得した3Dは保存済みモデル一覧に保存しました。条件が変わったためプレビューは開いていません。');return;}
   await window.imageWorkbench.openSaved(data.saved_model.preview_url);note('Poly Havenの3Dモデルを取得して保存しました。');
  }catch(e){note(e.message);}
  finally{importing=false;enabled();}
 }
 get('publicModelSearch').addEventListener('click',()=>search());get('publicModelMore').addEventListener('click',()=>{if(next!==null&&activeQuery===get('publicModelQuery').value.trim())search(next);});
 get('publicModelQuery').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();search();}});
})();
