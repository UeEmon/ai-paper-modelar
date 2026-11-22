const {test,expect}=require('@playwright/test');
test('text-only profile AI and vision-only simple 3D have separate catalogues and survive reload independently',async({page})=>{
 const requests=[];let proposed;
 await page.route('**/api/ai/models',r=>{
  const purpose=r.request().headers()['x-ai-model-purpose'];requests.push(purpose||'general');
  return r.fulfill({json:{ok:true,models:(purpose==='image3d'?['gemma4:12b']:['text-only','gemma4:12b']).map(id=>({id,name:id}))}});
 });
 await page.route('**/api/ai/test',r=>r.fulfill({json:{ok:true,vision_tested:r.request().headers()['x-ai-test-mode']==='image'}}));
 await page.route('**/api/proposals',r=>{proposed=r.request().headers();return r.fulfill({json:{provider:'ollama',proposals:[],notes:[]}});});
 await page.goto('/#settings');await page.locator('#aiName').fill('Separate');await page.locator('#aiPassword').fill('separate-passphrase');await page.locator('#aiCreate').click();
 await expect(page.locator('#aiMessage')).toContainText('作成しました');const id=await page.locator('#aiProfile').inputValue();
 await page.locator('#aiProvider').selectOption('ollama');await page.locator('#aiModels').click();await page.locator('#aiModelSelect').selectOption('text-only');
 await page.locator('#aiSave').click();await expect(page.locator('#aiMessage')).toContainText('暗号化して保存');
 await page.locator('#simpleProvider').selectOption('ollama');await page.locator('#simpleModels').click();
 await expect(page.locator('#simpleModel option')).toHaveCount(2);await expect(page.locator('#simpleModel option[value="text-only"]')).toHaveCount(0);
 await page.locator('#simpleModel').selectOption('gemma4:12b');await page.locator('#simpleSave').click();await expect(page.locator('#simpleMessage')).toContainText('暗号化して保存');
 expect(requests).toEqual(['general','image3d']);
 expect(await page.evaluate(()=>window.paperAI.headers()['X-AI-Model'])).toBe('text-only');
 expect(await page.evaluate(()=>window.paperAI.headersSimple3D()['X-AI-Model'])).toBe('gemma4:12b');
 await page.reload();await page.locator('#aiProfile').selectOption(id);await page.locator('#aiPassword').fill('separate-passphrase');await page.locator('#aiUnlock').click();
 await expect(page.locator('#aiModel')).toHaveValue('text-only');await expect(page.locator('#simpleModel')).toHaveValue('gemma4:12b');
 await page.getByRole('tab',{name:'資料・AI提案',exact:true}).click();await page.locator('#plan').click();await expect.poll(()=>proposed?.['x-ai-model']).toBe('text-only');
 await page.getByRole('tab',{name:'AI設定',exact:true}).click();await page.locator('#aiLock').click();
 expect(await page.evaluate(()=>window.paperAI.headersSimple3D())).toEqual({});
});

test('failed simple 3D image verification cannot replace either saved setting',async({page})=>{
 await page.route('**/api/ai/models',r=>r.fulfill({json:{ok:true,models:[{id:'vision-model',name:'vision-model'}]}}));
 await page.route('**/api/ai/test',r=>r.fulfill({status:422,json:{ok:false,vision_tested:false,message:'画像入力を確認できません'}}));
 await page.goto('/#settings');await page.locator('#aiName').fill('Fail');await page.locator('#aiPassword').fill('separate-passphrase');await page.locator('#aiCreate').click();
 await expect(page.locator('#aiMessage')).toContainText('作成しました');const before=await page.evaluate(()=>JSON.stringify(localStorage));
 await page.locator('#simpleProvider').selectOption('ollama');await page.locator('#simpleModels').click();await page.locator('#simpleModel').selectOption('vision-model');
 await page.locator('#simpleSave').click();await expect(page.locator('#simpleMessage')).toContainText('画像入力を確認できません');
 expect(await page.evaluate(()=>JSON.stringify(localStorage))).toBe(before);expect(await page.evaluate(()=>window.paperAI.headersSimple3D())).toEqual({});
});
