"use strict";
(function(){
  const get=id=>document.getElementById(id);
  const {AIVault,defaults,PREFIX}=window.PaperAIVault;
  let vault;
  const message=value=>{get("aiMessage").textContent=value;};
  function fields(){
    const provider=get("aiProvider").value,config=vault.data?.providers[provider];
    get("aiModel").value=config?.model||defaults[provider]||"";
    get("aiKey").value="";
    get("aiKey").placeholder=config?"保存済み（変更時だけ入力）":"APIキーを入力";
    get("aiModel").disabled=provider==="none";
    get("aiKey").disabled=provider==="none";
  }
  function render(){
    get("aiPassword").value="";get("aiKey").value="";
    get("aiEditor").disabled=!vault.data;
    get("aiProvider").value=vault.data?.provider||"none";fields();
    get("aiState").textContent=vault.data?"解除中 · "+(vault.data.provider==="none"?"定型案を使用":vault.data.provider+" を使用"):"ロック中 · 定型案を使用";
  }
  function profiles(selected=""){
    get("aiProfile").replaceChildren(new Option("プロファイルを選択", ""));
    for(const item of vault.list())get("aiProfile").add(new Option(item.name,item.id));
    get("aiProfile").value=selected;
  }
  let busy=false;
  async function action(work){
    if(busy)return;busy=true;
    for(const id of ["aiCreate","aiUnlock","aiSave","aiDelete"])get(id).disabled=true;
    try{await work();}catch(error){message(error.message);}
    finally{busy=false;for(const id of ["aiCreate","aiUnlock","aiSave","aiDelete"])get(id).disabled=false;render();}
  }
  try{
    if(!window.isSecureContext||!window.crypto?.subtle)throw Error();
    vault=new AIVault(window.localStorage,window.crypto);profiles();render();
  }catch{
    get("aiControls").disabled=true;
    message("暗号化保存を利用できません。HTTPSまたはlocalhostで開き、ブラウザ保存を許可してください。定型案は利用できます。");
    window.paperAI={headers:()=>({})};return;
  }
  window.paperAI={headers:()=>vault.headers()};
  get("aiProfile").addEventListener("change",()=>{vault.lock();render();message("選択したプロファイルを解除してください。");});
  get("aiProvider").addEventListener("change",fields);
  get("aiCreate").addEventListener("click",()=>action(async()=>{
    const id=await vault.create(get("aiName").value,get("aiPassword").value);
    profiles(id);get("aiName").value="";message("プロファイルを作成しました。AI設定を保存してください。");
  }));
  get("aiUnlock").addEventListener("click",()=>action(async()=>{
    await vault.unlock(get("aiProfile").value,get("aiPassword").value);message("解除しました。");
  }));
  get("aiSave").addEventListener("click",()=>action(async()=>{
    await vault.save(get("aiProvider").value,get("aiModel").value.trim(),get("aiKey").value.trim());message("暗号化して保存しました。");
  }));
  get("aiLock").addEventListener("click",()=>{vault.lock();render();message("ロックしました。");});
  get("aiDelete").addEventListener("click",()=>action(async()=>{
    const id=get("aiProfile").value;
    if(id&&window.confirm("選択したプロファイルのAI設定とキーを削除しますか？")){
      vault.remove(id);profiles();message("削除しました。");
    }
  }));
  window.addEventListener("pagehide",()=>{vault.lock();render();});
  window.addEventListener("storage",event=>{
    if(event.key===null||event.key.startsWith(PREFIX)){
      vault.lock();profiles();render();message("別タブで保存内容が変更されたためロックしました。");
    }
  });
})();
