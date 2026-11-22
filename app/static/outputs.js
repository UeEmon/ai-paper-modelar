"use strict";
(() => {
 const list=document.getElementById('outputList');
 async function refresh(){
  try{
   const response=await fetch('/api/outputs',{cache:'no-store'});if(!response.ok)throw Error();
   const data=await response.json();list.replaceChildren();
   if(!data.outputs.length)list.textContent='展開図を作成すると、ここから再ダウンロードできます。';
   for(const item of data.outputs){
    const row=document.createElement('p'),link=document.createElement('a'),button=document.createElement('button');
    link.href=item.url;link.textContent=item.id.slice(0,12)+'.'+item.id.split('.').pop()+'（'+Math.ceil(item.bytes/1024)+' KB）';link.download='paper-net.'+item.id.split('.').pop();
    button.type='button';button.textContent='削除';button.className='secondary';button.addEventListener('click',async()=>{
     if(!confirm('この展開図をサーバーから削除しますか？'))return;
     const result=await fetch(item.url,{method:'DELETE'});if(result.ok)refresh();else list.textContent='削除できませんでした。一覧を更新してください。';
    });row.append(link,' ',button);list.append(row);
   }
  }catch{list.textContent='展開図の一覧を取得できませんでした。';}
 }
 document.getElementById('refreshOutputs').addEventListener('click',refresh);refresh();
})();

(() => {
 const list=document.getElementById('generatedModelList');
 const add=(parent,tag,text)=>{const item=document.createElement(tag);item.textContent=text;parent.append(item);return item;};
 async function refresh(){
  try{
   const response=await fetch('/api/generated-models',{cache:'no-store'});if(!response.ok)throw Error('生成モデル一覧を取得できませんでした。');
   const data=await response.json();list.replaceChildren();
   if(!data.models.length)list.textContent='生成した3Dモデルは自動でここに保存されます。';
   for(const model of data.models){
    const row=add(list,'div','');row.className='savedGeneratedModel';
    add(row,'strong',model.name);add(row,'p',model.provider+' / '+model.faces+'三角形 / '+model.size_mm.join(' × ')+' mm');
    const actions=add(row,'div','');actions.className='projectButtons';
    const open=add(actions,'button','3Dを開く');open.type='button';open.className='secondary';
    open.addEventListener('click',async()=>{try{await window.imageWorkbench.openSaved(model.preview_url);}catch(e){list.textContent=e.message;}});
    const unfold=add(actions,'button','展開図を作る');unfold.type='button';
    unfold.addEventListener('click',async()=>{
     unfold.disabled=true;
     try{
      const response=await fetch(model.obj_url,{cache:'no-store'});if(!response.ok)throw Error('保存したOBJを取得できません。');
      const file=new File([await response.blob()],'generated-model.obj',{type:'text/plain'});
      document.getElementById('meshUnit').value='mm';document.getElementById('meshScale').value='1';
      await window.meshWorkbench.loadFile(file,{saveOriginal:false});
     }catch(e){list.textContent=e.message;}finally{unfold.disabled=false;}
    });
    for(const [url,label] of [[model.obj_url,'OBJを保存'],[model.glb_url,'生成GLBを保存']]){
     if(!url)continue;const link=add(actions,'a',label);link.href=url;link.download='generated-model.'+(label.includes('GLB')?'glb':'obj');
    }
    const remove=add(actions,'button','3Dを削除');remove.type='button';remove.className='secondary';
    remove.addEventListener('click',async()=>{
     if(!confirm('この生成3Dモデルをサーバーから削除しますか？'))return;
     const response=await fetch(model.preview_url,{method:'DELETE'});if(!response.ok){list.textContent='生成モデルを削除できませんでした。';return;}
     await refresh();
    });
   }
  }catch(e){list.textContent=e.message;}
 }
 document.getElementById('refreshModels').addEventListener('click',refresh);
 window.addEventListener('paper-generated-model-saved',refresh);refresh();
})();
