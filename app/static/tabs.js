"use strict";
(() => {
  const tabs=Array.from(document.querySelectorAll('[role="tab"]'));
  const ids=tabs.map(tab=>tab.id.slice(4));
  function refreshContext(){
    const select=document.getElementById("projectSelect");
    const project=select.value?select.selectedOptions[0]?.textContent:"一時作業（未保存）";
    const name=document.getElementById("place").value.trim()||"題材未入力";
    document.getElementById("workContext").textContent=name+" · "+project;
  }
  function show(id,{focus=false,record=true}={}){
    if(!ids.includes(id))return;
    for(const tab of tabs){
      const selected=tab.id==="tab-"+id;
      tab.setAttribute("aria-selected",String(selected));
      tab.tabIndex=selected?0:-1;
      document.getElementById(tab.getAttribute("aria-controls")).hidden=!selected;
    }
    if(record&&location.hash!=="#"+id)history.pushState(null,"","#"+id);
    refreshContext();
    if(focus){
      const tab=document.getElementById("tab-"+id);
      tab.focus({preventScroll:true});
      tab.scrollIntoView({block:"nearest",inline:"nearest"});
    }
  }
  for(const [index,tab] of tabs.entries()){
    tab.addEventListener("click",()=>show(ids[index]));
    tab.addEventListener("keydown",event=>{
      if(event.altKey||event.ctrlKey||event.metaKey)return;
      let next;
      if(event.key==="ArrowRight")next=(index+1)%tabs.length;
      if(event.key==="ArrowLeft")next=(index+tabs.length-1)%tabs.length;
      if(event.key==="Home")next=0;
      if(event.key==="End")next=tabs.length-1;
      if(next===undefined)return;
      event.preventDefault();show(ids[next],{focus:true});
    });
  }
  for(const button of document.querySelectorAll("[data-open-tab]")){
    button.addEventListener("click",()=>show(button.dataset.openTab,{focus:true}));
  }
  const restore=()=>show(ids.includes(location.hash.slice(1))?location.hash.slice(1):"design",{record:false});
  window.addEventListener("popstate",restore);
  window.addEventListener("hashchange",restore);
  document.getElementById("place").addEventListener("input",refreshContext);
  window.paperTabs={show,refreshContext};
  restore();
})();
