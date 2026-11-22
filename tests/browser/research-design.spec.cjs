const {test,expect}=require('@playwright/test');
const references=[
  {title:'海辺の灯台',url:'https://ja.wikipedia.org/wiki/灯台',summary:'円形の塔と上部の灯室が特徴。'},
  {title:'別の建物',url:'https://ja.wikipedia.org/wiki/建築',summary:'検索で一緒に見つかった建物。'}
];
const design={template:'cone',width_m:4,depth_m:4,height_m:16,top_ratio:0.65,roof:'flat',pitch_deg:0,overhang_m:0,sides:6};
const result=title=>({provider:'ollama',notes:[],proposals:[{title,style:'retro',description:'円形の塔を円すい台で表現します。',design,design_basis:'選択資料にある円形の塔を参考にした簡略形状。寸法は推定です。',source_indices:[1],dimensions_estimated:true}]});
async function search(page){
  await page.locator('#place').fill('海辺の灯台');await page.locator('#textSearch').click();
  await expect(page.locator('#researchState')).toContainText('1件をAIに使用');
}
test('selected search references become editable AI geometry and change the generated net',async({page})=>{
  let sent,model;
  await page.route('**/api/research?*',r=>r.fulfill({json:{results:references,note:'二次資料です。'}}));
  await page.route('**/api/proposals',r=>{sent=r.request().postDataJSON();return r.fulfill({json:result('灯室を強調した灯台')});});
  page.on('request',r=>{if(r.url().endsWith('/api/model'))model=r.postDataJSON();});
  await page.goto('/#shape');await page.locator('#generate').click();await expect(page.locator('#drawing')).toBeVisible();
  const oldPreview=await page.locator('#drawing').getAttribute('src');
  await page.getByRole('tab',{name:'資料・AI提案',exact:true}).click();await search(page);
  await page.locator('#plan').click();await expect(page.locator('#proposals')).toContainText('灯室を強調した灯台');
  expect(sent.sources).toEqual([references[0]]);
  await expect(page.locator('#proposals .draftDimensions')).toContainText('4 × 4 × 16');
  await expect(page.locator('#proposals a')).toHaveAttribute('href',references[0].url);
  await page.getByRole('button',{name:'設計案を基本形状へ反映',exact:true}).click();
  await expect(page.getByRole('tab',{name:'基本形状',exact:true})).toHaveAttribute('aria-selected','true');
  await expect(page.locator('#template')).toHaveValue('cone');await expect(page.locator('#width')).toHaveValue('4');
  await expect(page.locator('#height')).toHaveValue('16');await expect(page.locator('#topRatio')).toHaveValue('0.65');
  await expect(page.locator('#appliedDesign')).toContainText('寸法はAIの推定値');
  await expect(page.locator('#savePdf')).toBeDisabled();await expect(page.locator('#drawing')).toBeHidden();
  await page.locator('#generate').click();await expect(page.locator('#drawing')).toBeVisible();
  expect(model).toMatchObject({name:'海辺の灯台',template:'cone',width_m:4,depth_m:4,height_m:16,top_ratio:0.65,style:'retro'});
  expect(await page.locator('#drawing').getAttribute('src')).not.toBe(oldPreview);
  await expect(page.locator('#savePdf')).toBeEnabled();
  await page.screenshot({path:'test-results/research-applied-design.png',fullPage:true});
});
test('changing subject or failed search never sends previous references',async({page})=>{
  const sent=[];
  let fail=false;
  await page.route('**/api/research?*',r=>r.fulfill(fail?{status:503,json:{detail:'unavailable'}}:{json:{results:references,note:''}}));
  await page.route('**/api/proposals',r=>{sent.push(r.request().postDataJSON());return r.fulfill({json:result('資料を反映した案')});});
  await page.goto('/');await search(page);
  await page.locator('#place').fill('別の題材');await expect(page.locator('#research .reference')).toHaveCount(0);
  await page.locator('#plan').click();await expect.poll(()=>sent.length).toBe(1);expect(sent[0].sources).toEqual([]);
  await search(page);fail=true;await page.locator('#textSearch').click();await expect(page.locator('#researchState')).toContainText('検索できませんでした');
  await page.locator('#plan').click();await expect.poll(()=>sent.length).toBe(2);expect(sent[1].sources).toEqual([]);
});
test('late proposals from an old subject cannot overwrite a new proposal',async({page})=>{
  let finishOld,requests=0;
  await page.route('**/api/proposals',async r=>{
    requests++;
    if(requests===1){await new Promise(resolve=>{finishOld=resolve;});await r.fulfill({json:result('古い題材の案')});}
    else await r.fulfill({json:result('新しい題材の案')});
  });
  await page.goto('/');await page.locator('#plan').click();await expect.poll(()=>requests).toBe(1);
  await page.locator('#place').fill('新しい題材');await page.locator('#plan').click();await expect(page.locator('#proposals')).toContainText('新しい題材の案');
  const response=page.waitForResponse(r=>r.url().endsWith('/api/proposals')&&r.request().postDataJSON().place==='小さな洋館');
  finishOld();await response;await expect(page.locator('#proposals')).not.toContainText('古い題材の案');
});
test('unconfigured AI explains that offline styles do not interpret search results',async({page})=>{
  await page.route('**/api/research?*',r=>r.fulfill({json:{results:references,note:''}}));
  await page.goto('/');await search(page);await page.locator('#plan').click();
  await expect(page.locator('#proposals')).toContainText('検索資料からの形状・寸法の設計は行っていません');
  await expect(page.getByRole('button',{name:'設計案を基本形状へ反映',exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'AI設定を開く',exact:true}).click();
  await expect(page.getByRole('tab',{name:'AI設定',exact:true})).toHaveAttribute('aria-selected','true');
});
