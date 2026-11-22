const {test,expect}=require('@playwright/test');
test('external providers save separately, consent is required, and simple generation remains available',async({page})=>{
 let calls=0,seen;
 await page.route('**/api/3d/test',r=>r.fulfill({json:{ok:true,message:'接続確認'}}));
 await page.route('**/api/3d/generate',r=>{calls++;seen=r.request().headers();return r.fulfill({json:{provider:'meshy',name:'mesh',components:[],notes:[],warnings:['推定形状'],vertices:[[0,0,0],[10,0,0],[0,10,0]],faces:[[0,1,2]],colors:['#aaa'],size_mm:[10,10,10],obj:'v 0 0 0\nv 10 0 0\nv 0 10 0\nf 1 2 3'}});});
 await page.route('**/api/image-model/images?*',r=>r.fulfill({json:{images:[{id:'a'.repeat(32),title:'Sample',author:'Author',license:'CC0',source_url:'https://commons.wikimedia.org/wiki/File:Sample',preview_url:'/fake-3d-preview'}]}}));
 await page.route('**/fake-3d-preview',r=>r.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aE0sAAAAASUVORK5CYII=','base64')}));
 await page.goto('/#settings');await page.locator('#aiName').fill('3D profile');await page.locator('#aiPassword').fill('external-passphrase');await page.locator('#aiCreate').click();
 await expect(page.locator('#threeProvider')).toBeEnabled();
 await page.locator('#threeProvider').selectOption('meshy');await page.locator('#threeModel').selectOption('meshy-t2.5');await page.locator('#threeKey').fill('test-mesh-key');
 await page.locator('#threeSave').click();await expect(page.locator('#threeMessage')).toContainText('暗号化して保存');
 expect(await page.evaluate(()=>JSON.stringify(localStorage))).not.toContain('test-mesh-key');await expect(page.locator('#threeKey')).toHaveValue('');
 await page.getByRole('tab',{name:'画像→3D',exact:true}).click();await page.locator('#imageMethod').selectOption('external');
 await expect(page.locator('#imageMethodHint')).toContainText('meshy');
 await page.locator('#imageSearch').click();await page.locator('input[name=imageChoice]').check();await page.locator('#imageConsent').check();
 await expect(page.locator('#imageGenerate')).toBeDisabled();await page.locator('#externalCostConsent').check();await page.locator('#imageGenerate').click();
 await expect(page.locator('#imageMessage')).toContainText('3Dを生成しました');expect(calls).toBe(1);expect(seen['x-3d-key']).toBe('test-mesh-key');expect(seen['x-ai-key']).toBeUndefined();
 await page.locator('#imageMethod').selectOption('simple');await expect(page.locator('#externalCostLabel')).toBeHidden();await expect(page.locator('#imageGenerate')).toHaveText('選択画像から簡易3Dを生成');
 await page.getByRole('tab',{name:'AI設定',exact:true}).click();await page.locator('#aiLock').click();await expect(page.locator('#threeProvider')).toBeEnabled();await expect(page.locator('#threeKey')).toBeDisabled();
});

test('rendered outputs can be reopened and deleted while source uploads create no persistent library',async({page})=>{
 await page.goto('/#shape');await page.locator('#generate').click();await expect(page.locator('#drawing')).toBeVisible();
 await page.getByRole('tab',{name:'プロジェクト',exact:true}).click();await page.locator('#refreshOutputs').click();
 await expect(page.locator('#outputList a').first()).toBeVisible();
 await expect(page.getByText('参考資料や模型設定はメモリのみです。',{exact:false})).toBeVisible();
 page.on('dialog',d=>d.accept());
 const url=await page.locator('#outputList a').first().getAttribute('href');await page.locator('#outputList button').first().click();await expect(page.locator('#outputList a[href="'+url+'"]')).toHaveCount(0);expect((await page.request.get(url)).status()).toBe(404);
});


test('locked users can choose every external API and are guided to unlock only credentials',async({page})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/#settings');
 await expect(page.locator('#threeProvider')).toBeEnabled();
 await expect(page.locator('#threeLockMessage')).toContainText('作成するか');
 for(const [provider,model] of [['meshy','meshy-t2.5'],['tripo','P1-20260311'],['huggingface','TRELLIS.2']]){
  await page.locator('#threeProvider').selectOption(provider);await expect(page.locator('#threeModel option').first()).toHaveAttribute('value',model);
  await page.locator('#threeModel').selectOption(model);
 }
 await expect(page.locator('#threeKey')).toBeDisabled();await expect(page.locator('#threeSave')).toBeDisabled();await expect(page.locator('#threeTest')).toBeDisabled();
 await page.locator('#threeUnlockGuide').click();await expect(page.locator('#aiName')).toBeFocused();
 await page.locator('#threeProvider').selectOption('tripo');await page.locator('#threeModel').selectOption('P2-20260801');
 await page.locator('#aiName').fill('Selection profile');await page.locator('#aiPassword').fill('selection-passphrase');await page.locator('#aiCreate').click();
 await expect(page.locator('#threeKey')).toBeEnabled();await expect(page.locator('#threeUnlockGuide')).toBeHidden();
 await expect(page.locator('#threeProvider')).toHaveValue('tripo');await expect(page.locator('#threeModel')).toHaveValue('P2-20260801');
 await page.locator('#threeKey').fill('unsaved-secret');await page.locator('#aiLock').click();
 await expect(page.locator('#threeKey')).toHaveValue('');await expect(page.locator('#threeProvider')).toBeEnabled();
 await page.locator('#threeUnlockGuide').click();await expect(page.locator('#aiPassword')).toBeFocused();
 expect(errors).toEqual([]);
});
