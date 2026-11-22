"use strict";
(function(){
  const get=id=>document.getElementById(id);
  const {AIVault,defaults,endpoints,isLocal,PREFIX}=window.PaperAIVault;
  let threeModels={};
  let vault,modelRequest=0,modelController=null,settingsVersion=0;
  let localConfig={endpoints:{...endpoints},runtime:"native",automatic_host_mapping:false};
  async function refreshLocalConfig(){
    const response=await fetch("/api/ai/local-config",{cache:"no-store",redirect:"error"});
    if(!response.ok)throw Error("標準の接続先を確認できませんでした。");
    localConfig=await response.json();return localConfig;
  }
  function effectiveEndpoint(provider,value){
    if(localConfig.runtime==="docker"&&localConfig.automatic_host_mapping&&localConfig.endpoints[provider]){
      try{const url=new URL(value);if(["localhost","127.0.0.1","[::1]"].includes(url.hostname)&&value.replace(/\/+$/,"")===endpoints[provider])return localConfig.endpoints[provider];}catch{}
    }
    return value;
  }
  const message=value=>{get("aiMessage").textContent=value;};
  function fields(){
    settingsVersion++;
    const provider=get("aiProvider").value,config=vault.data?.providers[provider];
    get("aiLocal").hidden=!isLocal(provider);
    get("aiEndpoint").value=effectiveEndpoint(provider,config?.endpoint||localConfig.endpoints[provider]||endpoints[provider]||"");
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
    window.dispatchEvent(new Event("paper-ai-change"));
    get("threeCredentials").disabled=!vault.data;get("threeKey").value="";
    get("threeUnlockGuide").hidden=Boolean(vault.data);
    get("threeLockMessage").textContent=vault.data?"解除中です。選択したAPIのキーを入力し、接続を確認して保存してください。":"APIとモデルは選択できます。キーの入力・接続テスト・保存には、上のユーザープロファイルを作成するか、選択してパスフレーズで解除してください。";
    get("threeProvider").value=vault.data?.threeD?.provider||get("threeProvider").value||"huggingface";threeFields();
    get("aiState").textContent=vault.data?"解除中 · "+(vault.data.provider==="none"?"定型案を使用":vault.data.provider+" を使用"):"ロック中 · 定型案を使用";
  }
  function profiles(selected=""){
    get("aiProfile").replaceChildren(new Option("プロファイルを選択", ""));
    for(const item of vault.list())get("aiProfile").add(new Option(item.name,item.id));
    get("aiProfile").value=selected;
  }
  function threeFields(){
    const provider=get("threeProvider").value,config=vault.data?.threeD?.providers?.[provider],previous=get("threeModel").value;
    get("threeModel").replaceChildren(...(threeModels[provider]||[]).map(id=>new Option(id,id)));
    if(config&&threeModels[provider]?.includes(config.model))get("threeModel").value=config.model;
    else if(threeModels[provider]?.includes(previous))get("threeModel").value=previous;
    get("threeKey").value="";get("threeKey").placeholder=config?"保存済み（変更時のみ入力）":"APIキー / HFトークン";
  }
  let busy=false;
  async function action(work,{refresh=true}={}){
    if(busy)return;busy=true;
    for(const id of ["aiCreate","aiUnlock","aiSave","aiTest","aiTestImage","aiDelete","aiModels","aiResetEndpoint","threeTest","threeSave"])get(id).disabled=true;
    try{await work();}catch(error){message(error.message);}
    finally{busy=false;for(const id of ["aiCreate","aiUnlock","aiSave","aiTest","aiTestImage","aiDelete","aiModels","aiResetEndpoint","threeTest","threeSave"])get(id).disabled=false;if(refresh)render();get("aiModels").disabled=get("aiProvider").value==="none";}
  }
  try{
    if(!window.isSecureContext||!window.crypto?.subtle)throw Error();
    vault=new AIVault(window.localStorage,window.crypto);profiles();render();
  }catch{
    get("aiControls").disabled=true;
    message("暗号化保存を利用できません。HTTPSまたはlocalhostで開き、ブラウザ保存を許可してください。定型案は利用できます。");
    window.paperAI={headers:()=>({})};return;
  }
  refreshLocalConfig().catch(()=>{});
  fetch("/api/3d/models",{cache:"no-store"}).then(r=>{if(!r.ok)throw Error();return r.json();}).then(data=>{threeModels=data.providers;threeFields();}).catch(()=>{get("threeMessage").textContent="3Dモデル一覧を取得できません。再読込してください。";});
  get("threeUnlockGuide").addEventListener("click",()=>{
    const target=get(vault.list().length?"aiPassword":"aiName");
    target.scrollIntoView({block:"center",behavior:"smooth"});target.focus({preventScroll:true});
    message(vault.list().length?"上のユーザープロファイルを選び、パスフレーズを入力して「解除」を押してください。":"プロファイル名と12文字以上のパスフレーズを入力して「新規作成」を押してください。");
  });
  get("threeProvider").addEventListener("change",()=>{settingsVersion++;threeFields();});
  for(const id of ["threeModel","threeKey"])get(id).addEventListener("input",()=>{settingsVersion++;});
  async function testThree(save){
    const provider=get("threeProvider").value,model=get("threeModel").value,key=get("threeKey").value.trim();
    const data=vault.prepare3D(provider,model,key),epoch=vault.epoch,version=settingsVersion;
    get("threeMessage").textContent="3D APIへの接続を確認しています…";
    const response=await fetch("/api/3d/test",{method:"POST",headers:vault.headers3D(data),cache:"no-store",redirect:"error"});
    const result=await response.json();
    if(epoch!==vault.epoch||version!==settingsVersion)throw Error("設定が変わったため接続結果を破棄しました。");
    if(!response.ok||result.ok!==true)throw Error(result.detail||"3D APIに接続できません。");
    if(save){await vault.save3D(provider,model,key);get("threeKey").value="";window.dispatchEvent(new Event("paper-ai-change"));}
    get("threeMessage").textContent=save?"3D設定を暗号化して保存しました。簡易3D用のAI設定は維持しています。":result.message;
  }
  for(const [id,save] of [["threeTest",false],["threeSave",true]])get(id).addEventListener("click",()=>action(()=>testThree(save),{refresh:false}));

  get("aiResetEndpoint").addEventListener("click",()=>action(async()=>{
    const provider=get("aiProvider").value;
    const config=await refreshLocalConfig();
    const endpoint=config.endpoints?.[provider];
    if(!endpoint)throw Error("標準の接続先がサーバーの許可URLにありません。管理者の接続先設定を確認してください。");
    get("aiEndpoint").value=endpoint;resetModels();
    message("接続先を "+endpoint+" に戻しました。モデル一覧を取得して、接続を確認して保存してください。");
  },{refresh:false}));
  window.paperAI={headers:()=>vault.headers(),headers3D:()=>vault.headers3D()};
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
    return {provider,model,apiKey,options,data:vault.prepare(provider,model,apiKey,options),epoch:vault.epoch,settingsVersion};
  }
  function resetModels(){
    modelRequest++;modelController?.abort();modelController=null;
    get("aiModelSelect").replaceChildren(new Option("一覧を取得して選択", ""));
    get("aiModelSelect").disabled=true;
    get("aiModels").disabled=get("aiProvider").value==="none"||busy;
    get("aiModelsMessage").textContent="プロバイダーとAPIキー（ローカルは接続先）を設定して一覧を取得してください。モデルIDは手入力もできます。";
  }
  get("aiModelSelect").addEventListener("change",()=>{
    if(get("aiModelSelect").value){get("aiModel").value=get("aiModelSelect").value;settingsVersion++;}
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
      if(isLocal(candidate.provider)&&result.endpoint)get("aiEndpoint").value=result.endpoint;
      const select=get("aiModelSelect");select.replaceChildren(new Option("モデルを選択（IDは手入力も可能）", ""));
      for(const model of result.models)select.add(new Option(model.name===model.id?model.id:model.name+"（"+model.id+"）",model.id));
      select.disabled=result.models.length===0;
      syncModelSelection();
      get("aiModelsMessage").textContent=result.models.length?result.models.length+"件を取得しました。画像→簡易3D向けの候補です。画像対応テストで動作を確認してください。"+(result.truncated?" 一覧は一部です。必要なIDは手入力できます。":""):"画像→簡易3Dに必要な能力を確認できるモデルがありません。画像対応モデルの導入・能力情報を確認してください。IDを手入力して画像対応テストもできます。";
    }catch(error){if(request===modelRequest&&error.name!=="AbortError")get("aiModelsMessage").textContent=error instanceof TypeError?"一覧の取得に失敗しました。接続先を確認するかモデルIDを手入力してください。":error.message;}
    finally{if(request===modelRequest){modelController=null;get("aiModels").disabled=busy||get("aiProvider").value==="none";}}
  });
  for(const id of ["aiModel","aiKey","aiEndpoint","aiVision"])get(id).addEventListener("input",()=>{settingsVersion++;});
  async function testDraft(candidate,{image=false}={}){
    if(candidate.provider==="none")return;
    message(image?"確認用画像を送信し、画像対応を確認しています…":"接続を確認しています…ローカルモデルの初回読み込みには時間がかかる場合があります。");
    let response;
    try{
      response=await fetch("/api/ai/test",{method:"POST",headers:{...vault.headers(candidate.data),"X-AI-Test-Mode":image?"image":"text"},cache:"no-store",redirect:"error"});
    }catch{throw Error("接続テストを実行できませんでした。アプリサーバーとの通信を確認してください。");}
    if(candidate.epoch!==vault.epoch)throw Error("プロファイルが切り替わったため、接続テストの結果を破棄しました。");
    const result=await response.json().catch(()=>({}));
    if(candidate.epoch!==vault.epoch)throw Error("プロファイルが切り替わったため、接続テストの結果を破棄しました。");
    if(candidate.settingsVersion!==settingsVersion)throw Error("設定が変わったため、接続テストの結果を破棄しました。");
    if(!response.ok||result.ok!==true)throw Error(result.message||"接続テストに失敗しました。");
    if(image&&result.vision_tested!==true)throw Error("画像対応を確認できませんでした。画像対応モデルを確認してください。");
    if(isLocal(candidate.provider)&&result.endpoint){candidate.options.endpoint=result.endpoint;get("aiEndpoint").value=result.endpoint;}
  }
  get("aiTest").addEventListener("click",()=>action(async()=>{
    const candidate=draft();await testDraft(candidate);
    message(candidate.provider==="none"?"AIを使わないため、接続テストは不要です。":"接続テストに成功しました。保存するまで設定は変更されません。");
  },{refresh:false}));
  get("aiTestImage").addEventListener("click",()=>action(async()=>{
    const candidate=draft();await testDraft(candidate,{image:true});
    message(candidate.provider==="none"?"AIを使わないため、接続テストは不要です。":"画像入力と色の認識テストに成功しました。保存するまで設定は変更されません。");
  },{refresh:false}));
  get("aiSave").addEventListener("click",()=>action(async()=>{
    const candidate=draft();await testDraft(candidate,{image:isLocal(candidate.provider)&&candidate.options.vision});
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
