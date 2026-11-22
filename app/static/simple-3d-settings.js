"use strict";
window.initSimple3DSettings=({vault,action,endpoint})=>{
 const get=id=>document.getElementById(id),{isLocal}=window.PaperAIVault;
 let version=0;
 const message=value=>{get('simpleMessage').textContent=value;};
 function clearModels(){version++;get('simpleModel').replaceChildren(new Option('モデル一覧を取得してください',''));}
 function fields(){
  clearModels();const provider=get('simpleProvider').value,config=vault.data?.simple3D?.providers?.[provider];
  get('simpleLocal').hidden=!isLocal(provider);
  get('simpleEndpoint').value=config?.endpoint||endpoint(provider);
  get('simpleKey').value='';get('simpleKey').placeholder=config?'簡易3D用の保存済みキーを使用':'簡易3D用のAPIキーを入力';
  if(config)get('simpleModel').add(new Option(config.model+'（簡易3Dの保存済みモデル）',config.model));
  get('simpleModel').value=config?.model||'';
 }
 function render(){
  get('simpleCredentials').disabled=!vault.data;
  get('simpleProvider').value=vault.data?.simple3D?.provider||get('simpleProvider').value||'openai';
  fields();message(vault.data?'プロファイルのAIとは別に、画像対応モデルを選び画像接続テスト後に保存します。':'モデル・キーの設定には上のプロファイルを作成または解除してください。');
 }
 function draft(forModels=false){
  const provider=get('simpleProvider').value,model=forModels?'model-list':get('simpleModel').value,key=get('simpleKey').value.trim();
  if(!forModels&&!model)throw Error('簡易3D対応モデルを取得して選択してください。');
  const options={endpoint:get('simpleEndpoint').value.trim(),vision:true};
  const data=vault.prepareSimple3D(provider,model,key,options);
  return {provider,model,key,options,data,epoch:vault.epoch,version};
 }
 function current(candidate){if(candidate.epoch!==vault.epoch||candidate.version!==version)throw Error('設定が変わったため簡易3Dの接続結果を破棄しました。');}
 async function work(fn){await action(async()=>{try{await fn();}catch(e){message(e.message);}}, {refresh:false});}
 get('simpleProvider').addEventListener('change',fields);
 for(const id of ['simpleKey','simpleEndpoint'])get(id).addEventListener('input',clearModels);
 get('simpleModel').addEventListener('change',()=>{version++;});
 get('simpleModels').addEventListener('click',()=>work(async()=>{
  const candidate=draft(true);message('簡易3D対応モデルを取得しています…');
  const response=await fetch('/api/ai/models',{method:'POST',headers:{...vault.headersSimple3D(candidate.data),'X-AI-Model-Purpose':'image3d'},cache:'no-store',redirect:'error'});
  const result=await response.json();current(candidate);
  if(!response.ok||result.ok!==true||!Array.isArray(result.models))throw Error(result.message||'モデル一覧を取得できません。');
  const selected=get('simpleModel').value;
  get('simpleModel').replaceChildren(new Option('簡易3D対応モデルを選択',''),...result.models.map(m=>new Option(m.name===m.id?m.id:m.name+'（'+m.id+'）',m.id)));
  if(result.models.some(m=>m.id===selected))get('simpleModel').value=selected;
  if(result.endpoint)get('simpleEndpoint').value=result.endpoint;
  message(result.models.length?result.models.length+'件の簡易3D対応候補です。保存前に画像接続テストを行います。':'画像入力と部品構成の生成に対応するモデルを確認できませんでした。画像対応モデルの導入・能力情報を確認してください。');
 }));
 async function test(save){
  const candidate=draft();message('確認用画像で簡易3D用モデルの画像対応を確認しています…');
  const response=await fetch('/api/ai/test',{method:'POST',headers:{...vault.headersSimple3D(candidate.data),'X-AI-Test-Mode':'image'},cache:'no-store',redirect:'error'});
  const result=await response.json();current(candidate);
  if(!response.ok||result.ok!==true||result.vision_tested!==true)throw Error(result.message||'画像入力を確認できませんでした。');
  if(save){
   if(result.endpoint)candidate.options.endpoint=result.endpoint;
   await vault.saveSimple3D(candidate.provider,candidate.model,candidate.key,candidate.options);
   get('simpleKey').value='';window.dispatchEvent(new Event('paper-ai-change'));
  }
  message(save?'簡易3D設定を暗号化して保存しました。プロファイルのAI設定は変更していません。':'簡易3D用モデルの画像接続テストに成功しました。');
 }
 for(const [id,save] of [['simpleTest',false],['simpleSave',true]])get(id).addEventListener('click',()=>work(()=>test(save)));
 return {render,refreshDefaults(){if(!get('simpleEndpoint').value&&isLocal(get('simpleProvider').value))get('simpleEndpoint').value=endpoint(get('simpleProvider').value);}};
};
