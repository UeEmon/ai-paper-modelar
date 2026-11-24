"use strict";
(() => {
  const byId = id => document.getElementById(id);
  let job = null;
  let pageIndex = 0;

  function note(message, className) {
    const p = document.createElement("p");
    p.textContent = message;
    if (className) p.className = className;
    byId("meshResults").appendChild(p);
  }

  function clearUI() {
    byId("meshResults").replaceChildren();
    byId("meshViewer").hidden = true;
    job = null;
  }

  async function getError(response) {
    const info = await response.json().catch(() => ({}));
    return typeof info.detail === "string" ? info.detail
      : "ファイルの処理に失敗しました（HTTP " + response.status + "）";
  }

  function renderMetadata() {
    byId("meshResults").replaceChildren();
    const stats = job.stats;
    note("形式：" + stats.format + " ｜ 頂点 " + stats.vertices +
         " ｜ 三角形 " + stats.triangles +
         " ｜ 展開パーツ " + stats.islands +
         " ｜ 接着タブ " + stats.tabs +
         (stats.oriented ? " ｜ 山折り " + stats.mountain_folds +
           " ・谷折り " + stats.valley_folds : "") +
         (stats.seams !== undefined ? " ｜ 貼り合わせ番号 " + stats.seams : "") +
         " ｜ A4 " + job.pages + "ページ");
    note("模型サイズ（mm）： " + stats.size_mm.join(" × ") +
         " ／ 縮尺 1/" + stats.scale +
         " ／ 入力単位 " + stats.source_unit);
    for (const warning of job.warnings) note(warning, "warning");
  }

  function showPage() {
    if (!job) return;
    byId("meshPreview").src =
      "/api/mesh/jobs/" + encodeURIComponent(job.id) + "/pages/" + pageIndex + ".svg";
    byId("meshPageCount").textContent = (pageIndex + 1) + " / " + job.pages;
    byId("meshPrevious").disabled = pageIndex <= 0;
    byId("meshNext").disabled = pageIndex + 1 >= job.pages;
    byId("meshViewer").hidden = false;
  }

  async function generate(fileOverride = null) {
    const input = byId("meshFile");
    const file = fileOverride instanceof File ? fileOverride : input.files[0];
    if (!file) {note("OBJまたはSTLファイルを選択してください。", "warning");return;}
    if (!/\.(obj|stl)$/i.test(file.name) || file.size > 5 * 1024 * 1024) {
      byId("meshResults").replaceChildren();
      note("OBJ/STLファイル（5MB以内）を選んでください。", "warning");
      return;
    }
    const btn = byId("meshGenerate");
    btn.disabled = true;
    clearUI();
    note("ファイルを検査し、展開図を作成しています…");
    try {
      const payload = new FormData();
      payload.append("file", file);
      payload.append("source_unit", byId("meshUnit").value);
      payload.append("scale", byId("meshScale").value);
      payload.append("glue_tabs", String(byId("meshTabs").checked));
      const response = await fetch("/api/mesh/jobs", {method:"POST",body:payload});
      if (!response.ok) throw new Error(await getError(response));
      job = await response.json();
      pageIndex = 0;
      renderMetadata();
      showPage();
      const library = window.paperLibrary;
      if (library?.projectId && byId("meshSaveOriginal").checked) {
        try {
          const form = new FormData();
          form.append("file", file, file.name);
          form.append("view", "other");
          form.append("notes", "3Dモデル（座標単位："+byId("meshUnit").value+"、展開縮尺 1/"+byId("meshScale").value+"）");
          const response = await fetch(library.url("/assets"),{method:"POST",body:form});
          if (!response.ok) throw new Error(await getError(response));
          await library.refresh(library.projectId);
          note("原本を一時作業へ追加しました（ディスク保存なし）。");
        } catch (error) {
          note("展開図は作成できましたが原本保存に失敗："+error.message, "warning");
        }
      }
      try{sessionStorage.setItem("paper-modelar-last-mesh-job",job.id);}catch{}
    } catch (error) {
      byId("meshResults").replaceChildren();
      note(error.message, "warning");
    } finally {
      btn.disabled = false;
    }
  }

  async function download(url, filename) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(await getError(response));
    const href = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(href), 10000);
  }

  async function restore() {
    let saved = null;
    try{saved = sessionStorage.getItem("paper-modelar-last-mesh-job");}catch{}
    if (!saved || !/^[0-9a-f]{32}$/.test(saved)) return;
    try {
      const response = await fetch("/api/mesh/jobs/" + saved, {cache:"no-store"});
      if (!response.ok) return;
      job = await response.json();
      pageIndex = 0;
      renderMetadata();showPage();
    } catch {
      // A restarted server or expired job should not break the rest of the page.
    }
  }

  byId("meshGenerate").addEventListener("click", generate);
  byId("meshPrevious").addEventListener("click", () => {
    if (job && pageIndex > 0) {pageIndex--;showPage();}
  });
  byId("meshNext").addEventListener("click", () => {
    if (job && pageIndex + 1 < job.pages) {pageIndex++;showPage();}
  });
  byId("meshPdf").addEventListener("click", async () => {
    if (!job) return;
    try {
      await download("/api/mesh/jobs/" + job.id + "/template.pdf", "mesh-paper-net.pdf");
    } catch(error){note(error.message,"warning");}
  });
  byId("meshSvg").addEventListener("click", async () => {
    if (!job) return;
    try {
      await download("/api/mesh/jobs/" + job.id + "/pages/" + pageIndex + ".svg",
                     "mesh-paper-net-page-" + (pageIndex + 1) + ".svg");
    } catch(error){note(error.message,"warning");}
  });

  byId("meshPreview").addEventListener("error", () => {
    note("プレビューを表示できません。ジョブが期限切れの場合は再度アップロードしてください。","warning");
  });

  window.meshWorkbench = {
    loadFile: async (file, {saveOriginal=false}={}) => {
      window.paperTabs?.show("mesh",{focus:true});
      byId("meshSaveOriginal").checked = saveOriginal;
      await generate(file);
      if(!byId("meshViewer").hidden)byId("meshViewer").scrollIntoView({behavior:"smooth",block:"nearest"});
    }
  };
  restore();
})();
