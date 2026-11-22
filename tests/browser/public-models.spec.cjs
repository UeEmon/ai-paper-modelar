const {test,expect}=require('@playwright/test');
test('public model search shows attribution, requires consent and imports without AI credentials',async({page})=>{
 let request;
 const saved={id:'c'.repeat(32),name:'Wooden Table',provider:'Poly Haven',size_mm:[30,100,20],faces:4,preview_url:'/api/generated-models/'+('c'.repeat(32)),obj_url:'/api/generated-models/'+('c'.repeat(32))+'/model.obj',glb_url:null};
 await page.route('**/api/public-models?*',r=>r.fulfill({json:{models:[{id:'wooden_table',name:'Wooden Table',author:'Artist',license:'CC0',source_url:'https://polyhaven.com/a/wooden_table',polycount:1000}],total:1,next_offset:null}}));
 await page.route('**/api/public-models/import',r=>{request=r.request();return r.fulfill({json:{saved_model:saved}});});
 await page.route('**/api/generated-models/'+saved.id,r=>r.fulfill({json:{name:saved.name,provider:'Poly Haven',size_mm:saved.size_mm,vertices:[[0,0,0],[30,0,0],[0,100,0],[0,0,20]],faces:[[0,2,1],[0,1,3],[1,2,3],[2,0,3]],colors:[],components:[],notes:[],warnings:[],obj:'v 0 0 0\nv 30 0 0\nv 0 100 0\nv 0 0 20\nf 1 3 2\nf 1 2 4\nf 2 3 4\nf 3 1 4',saved_model:saved}}));
 await page.goto('/#mesh');await page.locator('#publicModelQuery').fill('机');await page.locator('#publicModelSearch').click();
 await expect(page.locator('#publicModelResults')).toContainText('Artist / CC0');
 const retrieve=page.getByRole('button',{name:'取得・保存して3Dを開く',exact:true});await expect(retrieve).toBeDisabled();
 await page.locator('#publicModelConsent').check();await page.locator('#publicModelHeight').fill('100');await expect(retrieve).toBeDisabled();await page.locator('#publicModelConsent').check();await retrieve.click();
 await expect(page.getByRole('tab',{name:'画像→3D',exact:true})).toHaveAttribute('aria-selected','true');await expect(page.locator('#imageModelInfo')).toContainText('Poly Haven');
 expect(request.postDataJSON()).toEqual({asset_id:'wooden_table',height_mm:100,consent:true});
 expect(request.headers()['x-ai-key']).toBeUndefined();expect(request.headers()['x-3d-key']).toBeUndefined();
 await expect(page.locator('#imageUnfold')).toBeEnabled();
});

test('changing a public model query clears old results and consent',async({page})=>{
 await page.route('**/api/public-models?*',r=>r.fulfill({json:{models:[{id:'chair',name:'Chair',license:'CC0',source_url:'https://polyhaven.com/a/chair'}],total:1,next_offset:null}}));
 await page.goto('/#mesh');await page.locator('#publicModelSearch').click();await expect(page.locator('#publicModelResults')).toContainText('Chair');await page.locator('#publicModelConsent').check();
 await page.locator('#publicModelQuery').fill('rock');await expect(page.locator('#publicModelResults')).toBeEmpty();await expect(page.locator('#publicModelConsent')).not.toBeChecked();
});
