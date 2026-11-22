const {test,expect}=require('@playwright/test');
test('persisted generated model can reopen a 3D preview, unfold and delete after a page reload',async({page})=>{
 const info={id:'b'.repeat(32),name:'保存した模型',provider:'ollama',created_at:'2026-11-23T00:00:00Z',size_mm:[20,20,20],faces:4,preview_url:'/api/generated-models/'+('b'.repeat(32)),obj_url:'/api/generated-models/'+('b'.repeat(32))+'/model.obj',glb_url:null};
 const obj='v 0 0 0\nv 20 0 0\nv 0 20 0\nv 0 0 20\nf 1 3 2\nf 1 2 4\nf 2 3 4\nf 3 1 4\n';let deleted=false;
 await page.route('**/api/generated-models',r=>r.fulfill({json:{models:deleted?[]:[info]}}));
 await page.route('**/api/generated-models/'+info.id,r=>{
  if(r.request().method()==='DELETE'){deleted=true;return r.fulfill({status:204});}
  return r.fulfill({json:{name:info.name,provider:'ollama',size_mm:info.size_mm,vertices:[[0,0,0],[20,0,0],[0,20,0],[0,0,20]],faces:[[0,2,1],[0,1,3],[1,2,3],[2,0,3]],colors:['#aaa','#aaa','#aaa','#aaa'],components:[],notes:[],warnings:[],obj,saved_model:info}});
 });
 await page.route('**/api/generated-models/'+info.id+'/model.obj',r=>r.fulfill({body:obj,contentType:'application/octet-stream'}));
 await page.goto('/#projects');await expect(page.locator('#generatedModelList')).toContainText('保存した模型');
 await page.reload();await page.getByRole('button',{name:'3Dを開く',exact:true}).click();
 await expect(page.getByRole('tab',{name:'画像→3D',exact:true})).toHaveAttribute('aria-selected','true');
 await expect(page.locator('#imageMessage')).toContainText('サーバーに保存した3Dモデルを開きました');await expect(page.locator('#imageObj')).toBeEnabled();
 await page.getByRole('tab',{name:'プロジェクト',exact:true}).click();
 await page.locator('#generatedModelList').getByRole('button',{name:'展開図を作る',exact:true}).click();
 await expect(page.locator('#meshPreview')).toBeVisible();await expect(page.getByRole('tab',{name:'3Dモデル',exact:true})).toHaveAttribute('aria-selected','true');
 await page.getByRole('tab',{name:'プロジェクト',exact:true}).click();page.on('dialog',d=>d.accept());
 await page.getByRole('button',{name:'3Dを削除',exact:true}).click();await expect(page.locator('#generatedModelList')).not.toContainText('保存した模型');
});
