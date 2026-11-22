"use strict";
(function(){
  const get=id=>document.getElementById(id);
  const {AIVault,defaults,endpoints,isLocal,PREFIX}=window.PaperAIVault;
  let vault,modelRequest=0,modelController=null;
  const message=value=>{get("aiMessage").textContent=value;};
  function fields(){
    const provider=get("aiProvider").value,config=vault.data?.providers[provider];
    get("aiLocal").hidden=!isLocal(provider);
    get("aiEndpoint").value=config?.endpoint||endpoints[provider]||"";
    get("aiVision").checked=config?.vision===true;
    get("aiKeyHint").textContent=isLocal(provider)?"APIキー（任意・空欄なら保存済みキーを維持）":"APIキー（空欄なら選択先の保存済みキーを維持）";
    get("aiModel").value=config?.model||defaults[provider]||"";
    get("aiKey").value="";
    get("aiKey").placeholder=config?"保存済み（変更時だけ入力）":"APIキーを入力";
    get("aiModel").disabled=provider==="none";
    get("aiKey").disabled=provider==="none";
    resetModels();
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
  async function action(work,{refresh=true}={}){
    if(busy)return;busy=true;
    for(const id of ["aiCreate","aiUnlock","aiSave","aiTest","aiDelete","aiModels"])get(id).disabled=true;
    try{await work();}catch(error){message(error.message);}
    finally{busy=false;for(const id of ["aiCreate","aiUnlock","aiSave","aiTest","aiDelete","aiModels"])get(id).disabled=false;if(refresh)render();get("aiModels").disabled=get("aiProvider").value==="none";}
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
  function draft({forModels=false}={}){
    const provider=get("aiProvider").value,model=forModels?"model-list":get("aiModel").value.trim(),apiKey=get("aiKey").value.trim();
    const options={endpoint:get("aiEndpoint").value.trim(),vision:get("aiVision").checked};
    return {provider,model,apiKey,options,data:vault.prepare(provider,model,apiKey,options),epoch:vault.epoch};
  }
  function resetModels(){
    modelRequest++;modelController?.abort();modelController=null;
    get("aiModelSelect").replaceChildren(new Option("一覧を取得して選択", ""));
    get("aiModelSelect").disabled=true;
    get("aiModels").disabled=get("aiProvider").value==="none"||busy;
    get("aiModelsMessage").textContent="プロバイダーとAPIキー（ローカルは接続先）を設定して一覧を取得してください。モデルIDは手入力もできます。";
  }
  get("aiModelSelect").addEventListener("change",()=>{
    if(get("aiModelSelect").value)get("aiModel").value=get("aiModelSelect").value;
  });
  function syncModelSelection(){
    const select=get("aiModelSelect"),id=get("aiModel").value;
    select.value=Array.from(select.options).some(option=>option.value===id)?id:"";
  }
  get("aiModel").addEventListener("input",syncModelSelection);
  for(const id of ["aiKey","aiEndpoint"])get(id).addEventListener("input",resetModels);
  get("aiModels").addEventListener("click",async()=>{
    if(busy||get("aiProvider").value==="none")return;
    resetModels();const request=modelRequest;
    const controller=new AbortController();modelController=controller;
    get("aiModels").disabled=true;get("aiModelsMessage").textContent="モデル一覧を取得しています…";
    try{
      const candidate=draft({forModels:true});
      const response=await fetch("/api/ai/models",{method:"POST",headers:vault.headers(candidate.data),cache:"no-store",redirect:"error",signal:controller.signal});
      const result=await response.json().catch(()=>({}));
      if(request!==modelRequest||candidate.epoch!==vault.epoch)return;
      if(!response.ok||result.ok!==true||!Array.isArray(result.models))throw Error(result.message||"モデル一覧を取得できませんでした。モデルIDを手入力することもできます。");
      const select=get("aiModelSelect");select.replaceChildren(new Option("モデルを選択（IDは手入力も可能）", ""));
      for(const model of result.models)select.add(new Option(model.name===model.id?model.id:model.name+"（"+model.id+"）",model.id));
      select.disabled=result.models.length===0;
      syncModelSelection();
      get("aiModelsMessage").textContent=result.models.length?result.models.length+"件を取得しました。テキスト生成に対応するモデルを選び、保存時の接続テストで確認してください。"+(result.truncated?" 一覧は一部です。必要なIDは手入力できます。":""):"モデルが見つかりません。ローカルモデルの導入状態や閲覧権限を確認するか、IDを手入力してください。";
    }catch(error){if(request===modelRequest&&error.name!=="AbortError")get("aiModelsMessage").textContent=error instanceof TypeError?"一覧の取得に失敗しました。接続先を確認するかモデルIDを手入力してください。":error.message;}
    finally{if(request===modelRequest){modelController=null;get("aiModels").disabled=busy||get("aiProvider").value==="none";}}
  });
  async function testDraft(candidate){
    if(candidate.provider==="none")return;
    message("接続を確認しています…ローカルモデルの初回読み込みには時間がかかる場合があります。");
    let response;
    try{
      response=await fetch("/api/ai/test",{method:"POST",headers:vault.headers(candidate.data),cache:"no-store",redirect:"error"});
    }catch{throw Error("接続テストを実行できませんでした。アプリサーバーとの通信を確認してください。");}
    if(candidate.epoch!==vault.epoch)throw Error("プロファイルが切り替わったため、接続テストの結果を破棄しました。");
    const result=await response.json().catch(()=>({}));
    if(candidate.epoch!==vault.epoch)throw Error("プロファイルが切り替わったため、接続テストの結果を破棄しました。");
    if(!response.ok||result.ok!==true)throw Error(result.message||"接続テストに失敗しました。");
  }
  get("aiTest").addEventListener("click",()=>action(async()=>{
    const candidate=draft();await testDraft(candidate);
    message(candidate.provider==="none"?"AIを使わないため、接続テストは不要です。":"接続テストに成功しました。保存するまで設定は変更されません。");
  },{refresh:false}));
  get("aiSave").addEventListener("click",()=>action(async()=>{
    const candidate=draft();await testDraft(candidate);
    if(candidate.epoch!==vault.epoch)throw Error("操作が切り替わりました。");
    await vault.save(candidate.provider,candidate.model,candidate.apiKey,candidate.options);
    render();message("接続を確認し、暗号化して保存しました。");
  },{refresh:false}));
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
