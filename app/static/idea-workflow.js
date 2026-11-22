"use strict";
(() => {
 const get=id=>document.getElementById(id),note=text=>{get('ideaMessage').textContent=text;};
 const add=(parent,tag,text)=>{const el=document.createElement(tag);el.textContent=text;parent.append(el);return el;};
 let selectionVersion=0,version=0,controller=null,context=null,importing=false;
 if(window.matchMedia('(max-width:930px)').matches)get('textProposalDetails').open=false;
 function snapshot(){return {word:get('place').value.trim(),genre:get('subjectType').value,kind:get('ideaReferenceKind').value,project:window.paperLibrary?.projectId||null};}
 function same(a,b){return JSON.stringify(a)===JSON.stringify(b);}
 function invalidate(){
  version++;selectionVersion++;get("search").disabled=false;controller?.abort();controller=null;context=null;
  for(const id of ['ideaDiagrams','ideaPhotos','ideaPublicModels'])get(id).replaceChildren();
  get('ideaPublicConsent').checked=false;window.imageWorkbench?.invalidateIdea();
  note('条件を変更しました。「資料・公開3Dを検索」で資料を選び直してください。');
 }
 function options(){
  const height=Number(get('ideaHeight').value);
  if(!Number.isFinite(height)||height<20||height>300)throw Error('完成する3Dの高さは20〜300mmで指定してください。');
  return {method:get('ideaMethod').value,height_mm:height};
 }
 function drawReferences(images,target,label){
  if(!images.length){add(target,'p',label+'が見つかりません。ワードを変えるか手持ちの資料を使用してください。');return;}
  for(const image of images){
   const card=add(target,'div','');card.className='imageCandidate';
   const img=document.createElement('img');img.src=image.preview_url;img.alt=image.title;img.loading='lazy';card.append(img);
   add(card,'strong',image.title);add(card,'small',(image.author||'作者は出典を確認')+' / '+image.license);
   const source=add(card,'a','出典・利用条件を確認');source.href=image.source_url;source.target='_blank';source.rel='noopener noreferrer';
   const button=add(card,'button',label+'から3Dを作る');button.type='button';button.className='secondary';
   img.addEventListener('error',()=>{button.disabled=true;add(card,'small','この資料を取得できません。別の候補を選んでください。');});
   button.addEventListener('click',()=>{
    try{if(!context||!same(context,snapshot()))throw Error('条件が変わっています。再検索してください。');
     window.imageWorkbench.prepareReference(image,{...context,...options(),reference_type:image.reference_type});
    }catch(e){note(e.message);}
   });
  }
 }
 function enablePublic(){for(const button of get('ideaPublicModels').querySelectorAll('button'))button.disabled=importing||!get('ideaPublicConsent').checked;}
 async function retrieve(model){
  if(importing||!get('ideaPublicConsent').checked||!context||!same(context,snapshot()))return;
  let sizing;try{sizing=options();}catch(e){note(e.message);return;}
  const request=version,selection=selectionVersion;importing=true;enablePublic();note('公開3Dを取得・保存しています…');
  try{
   const response=await fetch('/api/public-models/import',{method:'POST',headers:{'Content-Type':'application/json'},cache:'no-store',redirect:'error',body:JSON.stringify({asset_id:model.id,height_mm:sizing.height_mm,consent:true})});
   const data=await response.json();if(!response.ok)throw Error(data.detail||'公開3Dを取得できませんでした。');
   window.dispatchEvent(new Event('paper-generated-model-saved'));
   if(request!==version||selection!==selectionVersion)return;
   await window.imageWorkbench.openSaved(data.saved_model.preview_url);
  }catch(e){if(request===version)note(e.message);}
  finally{importing=false;enablePublic();}
 }
 async function search(){
  invalidate();const candidate=snapshot(),request=version;
  if(!candidate.word){note('対象のワードを入力してください。');return;}
  const pending=new AbortController();controller=pending;get("search").disabled=true;note('構造図・参考画像と公開3Dモデルを検索しています…');
  try{
   const response=await fetch('/api/idea/references?'+new URLSearchParams({word:candidate.word,genre:candidate.genre,kind:candidate.kind}),{cache:'no-store',signal:pending.signal});
   const data=await response.json();if(request!==version||!same(candidate,snapshot()))return;
   if(!response.ok)throw Error(data.detail||'資料を検索できませんでした。');context=candidate;
   drawReferences(data.diagrams,get('ideaDiagrams'),'構造図候補');drawReferences(data.photos,get('ideaPhotos'),'参考画像');
   for(const model of data.public_models){
    const row=add(get('ideaPublicModels'),'div','');row.className='savedGeneratedModel';add(row,'strong',model.name);add(row,'p','Poly Haven / '+(model.author||'作者は出典を確認')+' / '+model.license);
    const link=add(row,'a','公開モデルの出典・利用条件');link.href=model.source_url;link.target='_blank';link.rel='noopener noreferrer';
    const button=add(row,'button','この公開3Dを取得・保存して使う');button.type='button';button.className='secondary';button.addEventListener('click',()=>retrieve(model));
   }
   if(!data.public_models.length)add(get('ideaPublicModels'),'p','一致する公開3Dは見つかりませんでした。構造図・画像から作成するか、ワードを変えてください。');
   enablePublic();note('使う資料、または公開3Dを選択してください。'+(data.warnings||[]).join(' '));
   if(window.matchMedia('(max-width:930px)').matches)get('ideaMessage').scrollIntoView({block:'start',behavior:'smooth'});
  }catch(e){if(request===version&&e.name!=='AbortError')note(e.message);}
  finally{if(request===version){controller=null;get("search").disabled=false;}}
 }
 get('search').addEventListener('click',search);
 get('place').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();get('search').click();}});
 for(const [id,event] of [['place','input'],['subjectType','change'],['ideaReferenceKind','change']])get(id).addEventListener(event,invalidate);
 get('ideaPublicConsent').addEventListener('change',()=>{selectionVersion++;enablePublic();});
 for(const [id,event] of [['ideaHeight','input'],['ideaMethod','change']])get(id).addEventListener(event,()=>{selectionVersion++;get('ideaPublicConsent').checked=false;enablePublic();window.imageWorkbench?.invalidateIdea();});
 get('ideaMeshUnfold').addEventListener('click',async()=>{
  const file=get('ideaMeshFile').files[0],scale=Number(get('ideaMeshScale').value);
  if(!file){note('手持ちのOBJ/STLを選択してください。');return;}
  if(file.size>5*1024*1024||!Number.isInteger(scale)||scale<1||scale>500){note('ファイルは5MB以内、縮尺は1〜500の整数で指定してください。');return;}
  get('ideaMeshUnfold').disabled=true;
  try{get('meshUnit').value=get('ideaMeshUnit').value;get('meshScale').value=String(scale);await window.meshWorkbench.loadFile(file,{saveOriginal:false});}
  catch(e){note(e.message);}finally{get('ideaMeshUnfold').disabled=false;}
 });
 window.paperIdea={sync(){if(context&&!same(context,snapshot()))invalidate();}};
})();
