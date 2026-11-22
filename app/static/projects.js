"use strict";
/* Persistent single-user project library. Main editor helpers come from app.js. */
const paperLibrary = {
  projectId: null,
  assets: [],
  projects: [],
  selected: new Set(),
  selectedAssets(){return Array.from(this.selected).slice(0,8);},
  async uploadSelected(){
    if(!this.projectId)return;
    const files=Array.from(el("fileSelect").files||[]);
    if(!files.length){status("資料ファイルを選択してください");return;}
    if(this.assets.length+files.length>40){
      status("1プロジェクトの資料上限は40件です");return;
    }
    el("uploadButton").disabled=true;
    try{
      let count=0;
      for(const file of files){
        if(file.size>15*1024*1024)throw Error(file.name+" は15MBを超えています");
        const form=new FormData();
        form.append("file",file,file.name);
        form.append("view",el("viewType").value);
        form.append("notes",el("fileNotes").value);
        await this.request(this.url("/assets"),{method:"POST",body:form});
        count++;
      }
      el("fileSelect").value="";
      await this.refresh(this.projectId);
      status(count+"件をプロジェクトへ永続保存しました");
    }catch(error){status("資料を保存できませんでした");window.alert(error.message);}
    finally{el("uploadButton").disabled=false;}
  },
  url(path=""){
    return "/api/projects/"+encodeURIComponent(this.projectId)+path;
  },
  async request(url,options={}){
    const response=await fetch(url,options);
    if(!response.ok){
      const error=await response.json().catch(()=>({}));
      throw Error(typeof error.detail==="string"?error.detail:"通信エラー："+response.status);
    }
    return response.status===204?null:response.json();
  },
  async refresh(preferred){
    const result=await this.request("/api/projects");
    this.projects=result.projects;
    const chosen=preferred===undefined?this.projectId:preferred;
    const select=el("projectSelect");
    const copy=el("copyDestination");
    select.replaceChildren();copy.replaceChildren();
    const none=document.createElement("option");none.value="";
    none.textContent="未選択（一時的な作業）";select.appendChild(none);
    const noCopy=document.createElement("option");noCopy.value="";
    noCopy.textContent="複製先を選択";copy.appendChild(noCopy);
    for(const item of this.projects){
      const opt=document.createElement("option");
      opt.value=item.id;opt.textContent=item.name+" ("+item.asset_count+"件)";
      select.appendChild(opt);
      if(item.id!==chosen){
        const other=document.createElement("option");
        other.value=item.id;other.textContent=item.name;
        copy.appendChild(other);
      }
    }
    select.value=chosen&&this.projects.some(p=>p.id===chosen)?chosen:"";
    await this.open(select.value);
  },
  async open(projectId){
    this.projectId=projectId||null;
    this.assets=[];
    this.selected.clear();
    el("saveProject").disabled=!this.projectId;
    el("deleteProject").disabled=!this.projectId;
    el("uploadButton").textContent=this.projectId?"このプロジェクトに資料を保存":"一時資料を追加";
    if(this.projectId){
      const result=await this.request(this.url());
      const project=result.project;
      this.assets=result.assets;
      el("projectTitle").value=project.name;
      el("projectNotes").value=project.notes||"";
      const s=project.model_spec;
      if(s){
        el("place").value=s.name||project.name;
        el("subjectType").value=s.subject_type||"architecture";
        el("template").value=s.template||"building";
        const known=["1","12","24","35","48","72","100","150","160","80","87","220"];
        el("scale").value=known.includes(String(s.scale))?String(s.scale):"custom";
        el("custom").value=s.scale;
        const unit=unitFactors[s.input_unit]?s.input_unit:"m";
        el("unit").value=unit;
        currentInputUnit=unit;
        for(const [id,key] of [
          ["width","width_m"],["depth","depth_m"],["height","height_m"],
          ["overhang","overhang_m"]
        ]){
          if(s[key]!==undefined)el(id).value=formatInput(s[key]/unitFactors[unit]);
        }
        if(s.pitch_deg!==undefined)el("pitch").value=s.pitch_deg;
        if(s.roof!==undefined)el("roof").value=s.roof;
        updateDimensionLabels();updateTemplateHint();
        const radio=document.querySelector('input[name="style"][value="'+s.style+'"]');
        if(radio)radio.checked=true;
        hint();sizes();
      }
      try{localStorage.setItem("paper-modelar-project-id",this.projectId);}catch{}
    }else{
      try{localStorage.removeItem("paper-modelar-project-id");}catch{}
    }
    this.render();
  },
  async create(){
    const btn=el("newProject");btn.disabled=true;
    try{
      const name=el("projectTitle").value.trim()||el("place").value.trim();
      if(!name)throw Error("プロジェクト名を入力してください");
      const response=await this.request("/api/projects",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({
          name:name, notes:el("projectNotes").value,model_spec:getSpec()
        })
      });
      await this.refresh(response.id);
      status("「"+response.name+"」を作成しました");
    }catch(error){window.alert(error.message);}
    finally{btn.disabled=false;}
  },
  async save(){
    if(!this.projectId)return;
    const button=el("saveProject");button.disabled=true;
    try{
      await this.request(this.url(),{
        method:"PATCH",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({
          name:el("projectTitle").value,
          notes:el("projectNotes").value,
          model_spec:getSpec()
        })
      });
      await this.refresh(this.projectId);
      status("プロジェクトの設定とメモを保存しました");
    }catch(error){window.alert(error.message);}
    finally{button.disabled=false;}
  },
  async remove(){
    if(!this.projectId)return;
    if(!window.confirm("「"+el("projectTitle").value+"」と保存された原本を完全に削除しますか？"))return;
    try{
      await this.request(this.url(),{method:"DELETE"});
      this.projectId=null;
      el("projectTitle").value="";
      el("projectNotes").value="";
      await this.refresh("");
      status("プロジェクトを削除しました");
    }catch(error){window.alert(error.message);}
  },
  render(){
    const panel=el("storedAssets");panel.replaceChildren();
    if(!this.projectId){
      text(panel,"p","プロジェクトを作成・選択すると、写真と設計図を継続保存できます。","muted");
      return;
    }
    if(!this.assets.length){
      text(panel,"p","保存資料はまだありません。上のファイル選択から追加できます。","muted");
      return;
    }
    for(const item of this.assets){
      const card=text(panel,"div","","uploadItem savedItem");
      const img=document.createElement("img");
      img.src=item.preview_url;img.alt=item.name;
      img.loading="lazy";card.appendChild(img);
      const info=text(card,"div","","uploadMeta");
      text(info,"b",item.name);
      text(info,"small",item.view+" · "+item.kind+" · "+(item.size_bytes/1048576).toFixed(2)+"MB");
      if(item.notes)text(info,"small",item.notes);
      const actions=text(info,"div","","assetActions");
      const use=document.createElement("label");use.className="useAi";
      const checkbox=document.createElement("input");checkbox.type="checkbox";
      checkbox.checked=this.selected.has(item.id);
      checkbox.addEventListener("change",()=>{
        if(checkbox.checked&&this.selected.size>=8){
          checkbox.checked=false;status("AI参照に選べる保存資料は8件までです");return;
        }
        if(checkbox.checked)this.selected.add(item.id);
        else this.selected.delete(item.id);
      });
      use.appendChild(checkbox);text(use,"span","AI参照");actions.appendChild(use);
      const original=text(actions,"a","原本保存");
      original.href=item.original_url;
      original.setAttribute("download",item.name);
      const edit=text(actions,"button","情報編集","secondary");
      edit.type="button";
      edit.addEventListener("click",async()=>{
        const notes=window.prompt("資料メモ（400文字以内）",item.notes||"");
        if(notes===null)return;
        const view=window.prompt("方向：front / back / left / right / roof / plan / detail / other",item.view);
        if(view===null)return;
        if(!["front","back","left","right","roof","plan","detail","other"].includes(view)){
          status("方向は指定された値から選んでください");return;
        }
        try{
          await this.request(this.url("/assets/"+item.id),{
            method:"PATCH",headers:{"Content-Type":"application/json"},
            body:JSON.stringify({notes,view})
          });
          const result=await this.request(this.url());
          this.assets=result.assets;this.render();status("資料情報を更新しました");
        }catch(error){window.alert(error.message);}
      });
      const copy=text(actions,"button","別の制作物へ複製","secondary");
      copy.type="button";
      copy.addEventListener("click",async()=>{
        const destination=el("copyDestination").value;
        if(!destination){status("資料の複製先プロジェクトを選択してください");return;}
        copy.disabled=true;
        try{
          await this.request(this.url("/assets/"+item.id+"/copy"),{
            method:"POST",headers:{"Content-Type":"application/json"},
            body:JSON.stringify({target_project_id:destination})
          });
          await this.refresh(this.projectId);
          status("保存資料を別のプロジェクトへ複製しました");
        }catch(error){window.alert(error.message);}
        finally{copy.disabled=false;}
      });
      const del=text(actions,"button","削除","secondary");
      del.type="button";
      del.addEventListener("click",async()=>{
        if(!window.confirm("資料「"+item.name+"」と原本を削除しますか？"))return;
        try{
          await this.request(this.url("/assets/"+item.id),{method:"DELETE"});
          this.assets=this.assets.filter(x=>x.id!==item.id);
          this.selected.delete(item.id);
          this.render();status("資料を削除しました");
        }catch(error){window.alert(error.message);}
      });
    }
  }
};
window.paperLibrary=paperLibrary;

el("projectSelect").addEventListener("change",()=>{
  paperLibrary.open(el("projectSelect").value).catch(error=>window.alert(error.message));
});
el("newProject").addEventListener("click",()=>paperLibrary.create());
el("saveProject").addEventListener("click",()=>paperLibrary.save());
el("deleteProject").addEventListener("click",()=>paperLibrary.remove());

let previousProject=null;
try{previousProject=localStorage.getItem("paper-modelar-project-id");}catch{}
paperLibrary.refresh(previousProject).catch(error=>status("保存プロジェクトの読込に失敗: "+error.message));
