const {test,expect}=require('@playwright/test');
const drawing={id:'a'.repeat(32),title:'Bus blueprint',source_url:'https://commons.wikimedia.org/wiki/File:Bus.jpg',author:'Author',license:'CC0',preview_url:'/idea-preview',reference_type:'diagram'};
const obj='v 0 0 0\nv 20 0 0\nv 0 20 0\nv 0 0 20\nf 1 3 2\nf 1 2 4\nf 2 3 4\nf 3 1 4\n';
const model={name:'Bus',provider:'ollama',vertices:[[0,0,0],[20,0,0],[0,20,0],[0,0,20]],faces:[[0,2,1],[0,1,3],[1,2,3],[2,0,3]],colors:[],components:[],notes:[],warnings:[],size_mm:[20,20,20],obj};
async function sources(page){
 await page.route('**/idea-preview',r=>r.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aE0sAAAAASUVORK5CYII=','base64')}));
}
async function simple(page){
 await page.route('**/api/ai/models',r=>r.fulfill({json:{ok:true,models:[{id:'gemma4:12b',name:'gemma4:12b'}]}}));
 await page.route('**/api/ai/test',r=>r.fulfill({json:{ok:true,vision_tested:true}}));
 await page.goto('/#settings');await page.locator('#aiName').fill('Idea');await page.locator('#aiPassword').fill('idea-passphrase');await page.locator('#aiCreate').click();await expect(page.locator('#aiMessage')).toContainText('作成しました');
 await page.locator('#simpleProvider').selectOption('ollama');await page.locator('#simpleModels').click();await page.locator('#simpleModel').selectOption('gemma4:12b');await page.locator('#simpleSave').click();await expect(page.locator('#simpleMessage')).toContainText('暗号化して保存');
}
test('genre and word -> drawing -> simple 3D -> real mesh unfolding',async({page})=>{
 let query,sent,generations=0;
 await sources(page);await page.route('**/api/idea/references?*',r=>{query=new URL(r.request().url()).searchParams;return r.fulfill({json:{diagrams:[drawing],photos:[],public_models:[],warnings:[]}});});
 await page.route('**/api/image-model/generate',r=>{sent=r.request().postDataJSON();generations++;return r.fulfill({json:model});});
 await simple(page);await page.getByRole('tab',{name:'資料・AI提案',exact:true}).click();
 await page.locator('#subjectType').selectOption('vehicle');await page.locator('#place').fill('Bus');await page.locator('#search').click();
 await expect(page.locator('#ideaDiagrams')).toContainText('Bus blueprint');expect(query.get('genre')).toBe('vehicle');expect(query.get('word')).toBe('Bus');expect(generations).toBe(0);
 await page.locator('#ideaDiagrams').getByRole('button',{name:'構造図候補から3Dを作る',exact:true}).click();
 await expect(page.getByRole('tab',{name:'画像→3D',exact:true})).toHaveAttribute('aria-selected','true');await expect(page.locator('#imageGenerate')).toBeDisabled();expect(generations).toBe(0);
 await page.locator('#imageConsent').check();await page.locator('#imageGenerate').click();await expect(page.locator('#imageObj')).toBeEnabled();
 expect(sent).toMatchObject({subject_type:'vehicle',reference_type:'diagram',image_id:drawing.id,name:'Bus'});
 await page.locator('#imageUnfold').click();await expect(page.locator('#meshPreview')).toBeVisible();await expect(page.locator('#meshPdf')).toBeEnabled();
});
test('existing public 3D is offered beside references and can be obtained then unfolded without AI',async({page})=>{
 let imported=false;const saved={id:'d'.repeat(32),preview_url:'/api/generated-models/'+('d'.repeat(32))};
 await page.route('**/api/idea/references?*',r=>r.fulfill({json:{diagrams:[],photos:[],public_models:[{id:'table',name:'Table',provider:'Poly Haven',author:'Author',license:'CC0',source_url:'https://polyhaven.com/a/table'}],warnings:[]}}));
 await page.route('**/api/public-models/import',r=>{imported=true;return r.fulfill({json:{saved_model:saved}});});
 await page.route('**/api/generated-models/'+saved.id,r=>r.fulfill({json:{...model,provider:'Poly Haven',saved_model:saved}}));
 await page.goto('/');await page.locator('#subjectType').selectOption('prop');await page.locator('#place').fill('table');await page.locator('#search').click();
 const button=page.getByRole('button',{name:'この公開3Dを取得・保存して使う',exact:true});await expect(button).toBeDisabled();expect(imported).toBe(false);
 await page.locator('#ideaPublicConsent').check();await button.click();await expect(page.locator('#imageObj')).toBeEnabled();expect(imported).toBe(true);
 await page.locator('#imageUnfold').click();await expect(page.locator('#meshPreview')).toBeVisible();
});
test('hand-owned OBJ bypasses search and AI and uploads directly for unfolding',async({page})=>{
 await page.goto('/');await page.locator('#ideaMeshFile').setInputFiles({name:'owned.obj',mimeType:'application/octet-stream',buffer:Buffer.from(obj)});
 await page.locator('#ideaMeshUnit').selectOption('mm');await page.locator('#ideaMeshScale').fill('1');await page.locator('#ideaMeshUnfold').click();
 await expect(page.getByRole('tab',{name:'3Dモデル',exact:true})).toHaveAttribute('aria-selected','true');await expect(page.locator('#meshPreview')).toBeVisible();await expect(page.locator('#meshPdf')).toBeEnabled();
});
test('genre and keyword changes discard late source suggestions',async({page})=>{
 let finish;
 await page.route('**/api/idea/references?*',async r=>{await new Promise(resolve=>{finish=resolve;});await r.fulfill({json:{diagrams:[drawing],photos:[],public_models:[],warnings:[]}}).catch(()=>{});});
 await page.goto('/');await page.locator('#search').click();await expect.poll(()=>Boolean(finish)).toBe(true);await page.locator('#subjectType').selectOption('vehicle');await page.locator('#place').fill('New word');finish();
 await expect(page.locator('#ideaDiagrams')).toBeEmpty();await expect(page.locator('#ideaMessage')).toContainText('条件を変更');
});

test('mobile idea flow keeps supplemental text tools closed and source choices within the screen',async({page})=>{
 await page.setViewportSize({width:390,height:844});await sources(page);
 await page.route('**/api/idea/references?*',r=>r.fulfill({json:{diagrams:[drawing],photos:[],public_models:[],warnings:[]}}));
 await page.goto('/');await expect(page.locator('#textSearch')).toBeHidden();await page.locator('#place').fill('Bus');await page.locator('#search').click();
 await expect(page.locator('#ideaDiagrams')).toContainText('Bus blueprint');expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
 await page.locator('#ideaDiagrams').getByRole('button',{name:'構造図候補から3Dを作る',exact:true}).click();await expect(page.locator('#imageGenerate')).toBeVisible();
});
