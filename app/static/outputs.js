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
