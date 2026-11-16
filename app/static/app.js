"use strict";
const el = id => document.getElementById(id);
let sources = [], spec = null, currentPage = 0, pages = 0, previewURL = null;

const uploaded = [];
const UPLOAD_LIMIT = 8;
const REF_KEY = "paper-modelar-uploads-v1";

function cacheUploads(){
  try { sessionStorage.setItem(REF_KEY, JSON.stringify(uploaded.map(x => x.id))); }
  catch { /* browser may disable session storage */ }
}
function showUploads(){
  const list = el("uploaded"); list.replaceChildren();
  if(!uploaded.length){text(list,"p","アップロードされた資料はありません。","muted");return;}
  for(const item of uploaded){
    const box=text(list,"div","","uploadItem");
    const img=document.createElement("img");
    img.src=item.preview_url;
    img.alt=item.name+" のプレビュー（PDFは1ページ目）";
    img.loading="lazy";
    box.appendChild(img);
    const meta=text(box,"div","","uploadMeta");
    text(meta,"b",item.name);
    text(meta,"small",item.kind.toUpperCase()+" / "+item.view+" / "+(item.size_bytes/1048576).toFixed(1)+"MB");
    if(item.notes)text(meta,"small",item.notes);
    const del=text(box,"button","削除","secondary");
    del.type="button";del.setAttribute("aria-label",item.name+" を削除");
    del.addEventListener("click",async()=>{
      del.disabled=true;
      try{
        const r=await fetch("/api/uploads/"+encodeURIComponent(item.id),{method:"DELETE"});
        if(!r.ok && r.status!==404)throw Error("削除できませんでした。");
        const index=uploaded.findIndex(x=>x.id===item.id);
        if(index>=0)uploaded.splice(index,1);
        cacheUploads();showUploads();status("資料を削除しました");
      }catch(e){del.disabled=false;status(e.message);}
    });
    list.appendChild(box);
  }
}
async function restoreUploads(){
  let ids=[];
  try{ids=JSON.parse(sessionStorage.getItem(REF_KEY)||"[]");}catch{ids=[];}
  if(!Array.isArray(ids))ids=[];
  for(const id of ids.slice(0,UPLOAD_LIMIT)){
    if(typeof id!=="string"||!/^[0-9a-f]{32}$/.test(id))continue;
    try{
      const r=await fetch("/api/uploads/"+id,{cache:"no-store"});
      if(r.ok)uploaded.push(await r.json());
    }catch{/* expired or inaccessible */}
  }
  cacheUploads();showUploads();
}
async function addUploads(){
  if(window.paperLibrary&&window.paperLibrary.projectId){
    await window.paperLibrary.uploadSelected();
    return;
  }
  const files=Array.from(el("fileSelect").files||[]);
  if(!files.length){status("ファイルを選択してください。");return;}
  if(files.length+uploaded.length>UPLOAD_LIMIT){
    status("合計8件までです。不要な資料を削除してください。");return;
  }
  el("uploadButton").disabled=true;
  try{
    let added=0;
    for(const f of files){
      if(f.size>15*1024*1024)throw Error(f.name+" は15MBを超えています。");
      const body=new FormData();
      body.append("file",f,f.name);
      body.append("view",el("viewType").value);
      body.append("notes",el("fileNotes").value);
      const r=await fetch("/api/uploads",{method:"POST",body});
      if(!r.ok){
        const data=await r.json().catch(()=>({}));
        throw Error(f.name+": "+(typeof data.detail==="string"?data.detail:"アップロードに失敗"));
      }
      uploaded.push(await r.json());added++;
      cacheUploads();showUploads();
    }
    el("fileSelect").value="";
    status(added+"件を追加しました");
  }catch(e){status("追加エラー");window.alert(e.message);}
  finally{el("uploadButton").disabled=false;}
}

const hints = {
  "150":"日本型在来線のNゲージに適合（線路幅9mm）。",
  "160":"新幹線・外国型Nで一般的（線路幅9mm）。",
  "80":"日本型16番に多い縮尺（一般に線路幅16.5mm）。",
  "87":"HOスケール（一般に線路幅16.5mm）。",
  "220":"Zスケール（線路幅6.5mm）。",
  "custom":"縮尺分母を20～500で指定してください。"
};
function scale(){return Number(el("scale").value==="custom"?el("custom").value:el("scale").value);}
function getSpec(){
  return {
    name: el("place").value.trim() || "Model", scale:scale(),
    width_m:Number(el("width").value),depth_m:Number(el("depth").value),
    height_m:Number(el("height").value),pitch_deg:Number(el("pitch").value),
    overhang_m:Number(el("overhang").value),roof:el("roof").value,
    style:document.querySelector('input[name="style"]:checked').value
  };
}
function status(s){el("status").textContent=s;}
function text(parent,tag,value,cls){
  const item=document.createElement(tag);item.textContent=value;
  if(cls)item.className=cls;parent.appendChild(item);return item;
}
function hint(){
  el("custom").disabled=el("scale").value!=="custom";
  el("scaleGuide").textContent=hints[el("scale").value];
}
function sizes(){
  const s=getSpec();
  if(s.scale<20||s.scale>500){el("scaleResult").textContent="縮尺分母は20～500にしてください。";return;}
  const mm = m=>(m*1000/s.scale).toFixed(1);
  const rise=s.roof==="gable"?s.depth_m*500/s.scale*Math.tan(s.pitch_deg*Math.PI/180):0;
  el("scaleResult").textContent=
    "模型サイズ　幅 "+mm(s.width_m)+" × 奥行 "+mm(s.depth_m)+" × 全高 "+
    (Number(mm(s.height_m))+rise).toFixed(1)+" mm（軒の出は別）\n"+
    "人物170cm： "+mm(1.7)+" mm　／　扉2m： "+mm(2)+" mm";
}
async function post(url,value){
  const r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(value)});
  if(!r.ok){const d=await r.json().catch(()=>({}));throw Error(typeof d.detail==="string"?d.detail:"入力値または通信を確認してください");}
  return r;
}
async function search(){
  const area=el("research");area.replaceChildren();
  el("search").disabled=true;status("公開資料を検索中");
  try{
    const q=el("place").value.trim();
    if(q.length<2)throw Error("検索語を2文字以上で入力してください。");
    const r=await fetch("/api/research?q="+encodeURIComponent(q));
    if(!r.ok)throw Error("Wikipediaへの接続に失敗しました。");
    const data=await r.json();sources=data.results;
    for(const src of sources){
      const card=text(area,"div","","reference");
      const link=text(card,"a",src.title);link.href=src.url;link.target="_blank";link.rel="noopener noreferrer";
      text(card,"p",src.summary||"概要なし");
      text(card,"small","二次資料・寸法未検証","muted");
    }
    text(area,"p",data.note,"muted");status(sources.length+"件の資料を取得");
  }catch(e){text(area,"p",e.message,"warning");status("資料検索に失敗");}
  finally{el("search").disabled=false;}
}
async function plan(){
  const area=el("proposals");area.replaceChildren();
  el("plan").disabled=true;status("デザイン案を作成中");
  try{
    const r=await post("/api/proposals",{
      place:el("place").value.trim(),scale:scale(),style:getSpec().style,
      sources:sources.map(s=>({title:s.title,url:s.url,summary:s.summary})),
      upload_ids:uploaded.map(u=>u.id),
      project_id:window.paperLibrary?.projectId||null,
      project_asset_ids:window.paperLibrary?.selectedAssets()||[],
      include_uploads:el("allowAiUploads").checked
    });
    const result=await r.json();
    for(const p of result.proposals){
      const card=text(area,"div","","proposal");
      text(card,"strong",p.title);
      text(card,"p",p.description);
      const option=document.querySelector('input[name="style"][value="'+p.style+'"]');
      if(option){
        const b=text(card,"button","適用","secondary");
        b.addEventListener("click",()=>{option.checked=true;status("スタイルを更新しました");});
      }
    }
    for(const note of result.notes)text(area,"p",note,"muted");
    status(result.provider==="offline"?"定型案を表示":"AI提案を表示");
  }catch(e){text(area,"p",e.message,"warning");status("提案に失敗");}
  finally{el("plan").disabled=false;}
}
async function showPage(){
  const r=await post("/api/template.svg?page="+currentPage,spec);
  const blob=await r.blob();
  if(previewURL)URL.revokeObjectURL(previewURL);
  previewURL=URL.createObjectURL(blob);
  el("drawing").src=previewURL;el("drawing").hidden=false;el("placeholder").hidden=true;
  el("page").textContent=(currentPage+1)+" / "+pages;
  el("prev").disabled=currentPage===0;el("next").disabled=currentPage===pages-1;
  el("savePdf").disabled=false;el("saveSvg").disabled=false;
}
async function generate(){
  el("generate").disabled=true;status("展開図を計算中");
  try{
    spec=getSpec();
    const r=await post("/api/model",spec);
    const model=await r.json();pages=model.pages;currentPage=0;
    await showPage();status(pages+"ページを生成しました");
  }catch(e){window.alert(e.message);status("生成に失敗");}
  finally{el("generate").disabled=false;}
}
function save(blob,filename){
  const url=URL.createObjectURL(blob);const a=document.createElement("a");
  a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);
}
async function svg(){
  if(!spec)return;
  try{const r=await post("/api/template.svg?page="+currentPage,spec);
    save(await r.blob(),"paper-model-page-"+(currentPage+1)+".svg");
  }catch(e){window.alert(e.message);}
}
async function pdf(){
  if(!spec)return;el("savePdf").disabled=true;status("PDFを作成中");
  try{const r=await post("/api/template.pdf",spec);
    save(await r.blob(),"paper-model-1-"+spec.scale+".pdf");status("PDFを保存しました");
  }catch(e){window.alert(e.message);status("PDFに失敗");}
  finally{el("savePdf").disabled=false;}
}
el("search").addEventListener("click",search);
el("uploadButton").addEventListener("click",addUploads);
el("plan").addEventListener("click",plan);
el("generate").addEventListener("click",generate);
el("saveSvg").addEventListener("click",svg);
el("savePdf").addEventListener("click",pdf);
el("prev").addEventListener("click",async()=>{currentPage--;try{await showPage();}catch(e){window.alert(e.message);}});
el("next").addEventListener("click",async()=>{currentPage++;try{await showPage();}catch(e){window.alert(e.message);}});
el("scale").addEventListener("change",()=>{hint();sizes();});
for(const id of ["custom","width","depth","height","overhang","pitch","roof"]){
  el(id).addEventListener("input",sizes);
}
hint();sizes();
restoreUploads();
