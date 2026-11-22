"use strict";
(() => {
  const get=id=>document.getElementById(id);
  let selected=null,model=null,version=0,searchVersion=0,yaw=-0.55,pitch=-0.25,zoom=1,drag=null,generating=false;
  const canvas=get("imageCanvas"),ctx=canvas.getContext("2d");
  const note=text=>{get("imageMessage").textContent=text;};
  const add=(parent,tag,value)=>{const item=document.createElement(tag);item.textContent=value;parent.appendChild(item);return item;};
  function clearModel(){model=null;get("imageModelInfo").hidden=true;get("imagePlaceholder").hidden=false;get("imageObj").disabled=true;get("imageUnfold").disabled=true;draw();}
  function controls(){get("imageGenerate").disabled=generating||!selected||!get("imageConsent").checked;}
  function draw(){
    const rect=canvas.getBoundingClientRect();if(!rect.width)return;
    const ratio=window.devicePixelRatio||1;canvas.width=rect.width*ratio;canvas.height=rect.height*ratio;
    ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,rect.width,rect.height);if(!model)return;
    const extent=Math.max(...model.size_mm),scale=Math.min(rect.width,rect.height)*.65/extent*zoom;
    const points=model.vertices.map(([x,y,z])=>{
      y-=model.size_mm[1]/2;
      const a=x*Math.cos(yaw)+z*Math.sin(yaw),b=-x*Math.sin(yaw)+z*Math.cos(yaw);
      const c=y*Math.cos(pitch)-b*Math.sin(pitch),d=y*Math.sin(pitch)+b*Math.cos(pitch);
      const perspective=1/(1+d/(extent*4));return [rect.width/2+a*scale*perspective,rect.height/2-c*scale*perspective,d];
    });
    const faces=model.faces.map((face,i)=>({face,i,depth:face.reduce((sum,v)=>sum+points[v][2],0)/3})).sort((a,b)=>b.depth-a.depth);
    for(const {face,i} of faces){
      ctx.beginPath();face.forEach((v,index)=>{const p=points[v];if(index)ctx.lineTo(p[0],p[1]);else ctx.moveTo(p[0],p[1]);});ctx.closePath();
      ctx.fillStyle=model.colors[i]||"#c9b38b";ctx.fill();ctx.strokeStyle="#344a3c70";ctx.lineWidth=.65;ctx.stroke();
    }
  }
  new ResizeObserver(()=>draw()).observe(canvas);
  canvas.addEventListener("pointerdown",e=>{drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);});
  canvas.addEventListener("pointermove",e=>{if(!drag)return;yaw+=(e.clientX-drag[0])*.01;pitch=Math.max(-1.3,Math.min(1.3,pitch+(e.clientY-drag[1])*.01));drag=[e.clientX,e.clientY];draw();});
  for(const event of ["pointerup","pointercancel","lostpointercapture"])canvas.addEventListener(event,()=>{drag=null;});
  function setZoom(value){zoom=Math.max(.5,Math.min(2.5,value));get("imageZoom").value=zoom;draw();}
  canvas.addEventListener("wheel",e=>{e.preventDefault();setZoom(zoom-e.deltaY*.001);},{passive:false});
  canvas.addEventListener("keydown",e=>{
    if(e.altKey||e.ctrlKey||e.metaKey)return;
    if(!["ArrowLeft","ArrowRight","ArrowUp","ArrowDown","+","-"].includes(e.key))return;
    e.preventDefault();if(e.key==="ArrowLeft")yaw-=.15;if(e.key==="ArrowRight")yaw+=.15;
    if(e.key==="ArrowUp")pitch=Math.max(-1.3,pitch-.1);if(e.key==="ArrowDown")pitch=Math.min(1.3,pitch+.1);
    if(e.key==="+")setZoom(zoom+.1);if(e.key==="-")setZoom(zoom-.1);draw();
  });
  get("imageZoom").addEventListener("input",()=>setZoom(Number(get("imageZoom").value)));
  get("imageResetView").addEventListener("click",()=>{yaw=-.55;pitch=-.25;setZoom(1);});
  get("imageConsent").addEventListener("change",()=>{version++;controls();});
  get("imageHeight").addEventListener("input",()=>{version++;clearModel();controls();note("高さを変更しました。もう一度3Dを生成してください。");});
  function resetSearch(){
    searchVersion++;version++;selected=null;get("imageSearch").disabled=false;
    get("imageConsent").checked=false;get("imageCandidates").replaceChildren();clearModel();controls();note("検索語を変更しました。画像検索を押してください。");
  }
  get("imageQuery").addEventListener("input",resetSearch);
  get("place").addEventListener("input",()=>{if(!get("imageQuery").value.trim())resetSearch();});
  get("imageSearch").addEventListener("click",async()=>{
    const request=++searchVersion;version++;selected=null;get("imageConsent").checked=false;controls();clearModel();get("imageCandidates").replaceChildren();
    const query=get("imageQuery").value.trim()||get("place").value.trim();
    get("imageSearch").disabled=true;note("画像を検索しています…");
    try{
      const response=await fetch("/api/image-model/images?q="+encodeURIComponent(query),{cache:"no-store"});const data=await response.json();
      if(request!==searchVersion)return;if(!response.ok)throw Error(data.detail||"画像を検索できませんでした。");
      for(const image of data.images){
        const card=add(get("imageCandidates"),"div","");card.className="imageCandidate";
        const img=document.createElement("img");img.src=image.preview_url;img.alt=image.title;img.loading="lazy";card.appendChild(img);
        const label=add(card,"label","");const radio=document.createElement("input");radio.type="radio";radio.name="imageChoice";radio.value=image.id;label.appendChild(radio);add(label,"span",image.title);
        img.addEventListener("error",()=>{
          radio.disabled=true;add(card,"small","プレビューを取得できません。別の画像を選んでください。");
          if(selected?.id===image.id){selected=null;version++;get("imageConsent").checked=false;clearModel();controls();}
        });
        const source=add(card,"a","出典・利用条件を確認");source.href=image.source_url;source.target="_blank";source.rel="noopener noreferrer";
        add(card,"small",(image.author||"作者は出典で確認")+" / "+image.license);
        radio.addEventListener("change",()=>{selected=image;version++;get("imageConsent").checked=false;clearModel();controls();note("出典と利用条件を確認して、AIへの画像送信にチェックを入れてください。");});
      }
      note(data.images.length?"画像を1枚選んでください。":"画像が見つかりません。英語の名前や別の語句でも試してください。");
    }catch(error){if(request===searchVersion)note(error.message);}
    finally{if(request===searchVersion)get("imageSearch").disabled=false;}
  });
  get("imageGenerate").addEventListener("click",async()=>{
    if(generating||!selected||!get("imageConsent").checked)return;
    const request=++version,image=selected,headers=window.paperAI.headers();
    if(!headers["X-AI-Provider"]){note("AI設定でプロファイルを解除し、画像対応モデルを保存してください。");return;}
    generating=true;get("imageGenerate").disabled=true;clearModel();note("画像をAIで読み取り、簡易3Dモデルを生成しています…");
    try{
      const response=await fetch("/api/image-model/generate",{method:"POST",headers:{"Content-Type":"application/json",...headers},cache:"no-store",redirect:"error",body:JSON.stringify({image_id:image.id,name:(get("imageQuery").value.trim()||get("place").value.trim()||"画像からの模型").slice(0,80),height_mm:Number(get("imageHeight").value),consent:true})});
      const data=await response.json();if(request!==version)return;if(!response.ok)throw Error(typeof data.detail==="string"?data.detail:"3D生成に失敗しました。");
      if(JSON.stringify(headers)!==JSON.stringify(window.paperAI.headers())){note("AI設定が変わったため、生成結果を破棄しました。");return;}
      model=data;get("imagePlaceholder").hidden=true;get("imageModelInfo").hidden=false;get("imageModelInfo").replaceChildren();
      add(get("imageModelInfo"),"strong",data.components.length+"部品 / "+data.faces.length+"三角形 / 幅×高さ×奥行 "+data.size_mm.join(" × ")+" mm");
      for(const text of [...data.warnings,...data.notes])add(get("imageModelInfo"),"p",text);
      get("imageObj").disabled=false;get("imageUnfold").disabled=false;draw();note("簡易3Dを生成しました。回転して形状を確認できます。");
    }catch(error){if(request===version)note(error.message);}
    finally{generating=false;controls();}
  });
  function file(){return new File([model.obj],model.name.replace(/[\\/:*?"<>|]/g,"_").slice(0,60)+".obj",{type:"text/plain"});}
  get("imageObj").addEventListener("click",()=>{if(model)save(file(),file().name);});
  get("imageUnfold").addEventListener("click",async()=>{
    if(!model)return;get("meshUnit").value="mm";get("meshScale").value="1";
    await window.meshWorkbench.loadFile(file(),{saveOriginal:get("imageSaveOriginal").checked});
  });
})();
