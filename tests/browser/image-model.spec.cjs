const {test,expect}=require('@playwright/test');
const photo={id:'a'.repeat(32),title:'模型の建物.jpg',source_url:'https://commons.wikimedia.org/wiki/File:House.jpg',author:'Photographer',license:'CC BY-SA 4.0',preview_url:'/api/image-model/images/'+('a'.repeat(32))+'/preview'};
const vertices=[[-30,0,-20],[30,0,-20],[30,100,-20],[-30,100,-20],[-30,0,20],[30,0,20],[30,100,20],[-30,100,20]];
const quads=[[0,3,2,1],[4,5,6,7],[0,1,5,4],[3,7,6,2],[0,4,7,3],[1,2,6,5]];
const faces=quads.flatMap(q=>[[q[0],q[1],q[2]],[q[0],q[2],q[3]]]);
const obj=['# Reference: '+photo.source_url,...vertices.map(v=>'v '+v.join(' ')),...faces.map(f=>'f '+f.map(i=>i+1).join(' '))].join('\n')+'\n';
const model={name:'模型の建物',vertices,faces,colors:faces.map(()=>'#c9b38b'),obj,size_mm:[60,100,40],components:[{shape:'box'}],notes:['裏側は推定です。'],warnings:['単一画像からAIが推定した簡易3Dです。'],estimated:true};
async function mockImages(page){
  await page.route('**/api/image-model/images?*',r=>r.fulfill({json:{images:[photo]}}));
  await page.route('**/api/image-model/images/*/preview',r=>r.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aE0sAAAAASUVORK5CYII=','base64')}));
}
async function ai(page){
  await page.route('**/api/ai/test',r=>r.fulfill({json:{ok:true,vision_tested:true}}));
  await page.goto('/#settings');await page.locator('#aiName').fill('画像用AI');await page.locator('#aiPassword').fill('image-passphrase');await page.locator('#aiCreate').click();
  await expect(page.locator('#aiMessage')).toContainText('作成しました');
  await page.locator('#aiProvider').selectOption('openai');await page.locator('#aiKey').fill('test-image-key');await page.locator('#aiSave').click();
  await expect(page.locator('#aiMessage')).toContainText('暗号化して保存しました');
  await page.route('**/api/ai/models',r=>r.fulfill({json:{ok:true,models:[{id:'gpt-4.1-mini',name:'gpt-4.1-mini'}]}}));
  await page.locator('#simpleProvider').selectOption('openai');await page.locator('#simpleKey').fill('test-image-key');
  await page.locator('#simpleModels').click();await page.locator('#simpleModel').selectOption('gpt-4.1-mini');await page.locator('#simpleSave').click();
  await expect(page.locator('#simpleMessage')).toContainText('暗号化して保存');
  await page.getByRole('tab',{name:'画像→3D',exact:true}).click();
}
async function select(page){
  await page.locator('#imageQuery').fill('模型の建物');await page.locator('#imageSearch').click();
  await expect(page.locator('.imageCandidate img')).toBeVisible();
  await page.locator('input[name=imageChoice]').check();
}
test('search photo, consent, generate preview, save OBJ and unfold through the real mesh engine',async({page})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  let sent;
  await mockImages(page);await page.route('**/api/image-model/generate',r=>{sent=r.request().postDataJSON();expect(r.request().headers()['x-ai-key']).toBe('test-image-key');return r.fulfill({json:model});});
  await ai(page);await select(page);
  await expect(page.locator('#imageCandidates')).toContainText('CC BY-SA 4.0');
  await expect(page.locator('#imageGenerate')).toBeDisabled();
  await page.locator('#imageHeight').fill('100');await page.locator('#imageConsent').check();await page.locator('#imageGenerate').click();
  await expect(page.locator('#imageMessage')).toContainText('3Dを生成しました');
  expect(sent).toMatchObject({image_id:photo.id,height_mm:100,consent:true});
  expect(JSON.stringify(sent)).not.toContain('test-image-key');
  await expect(page.locator('#imageModelInfo')).toContainText('12三角形');
  await page.locator('#imageCanvas').focus();await page.keyboard.press('ArrowRight');
  const download=page.waitForEvent('download');await page.locator('#imageObj').click();expect((await download).suggestedFilename()).toBe('模型の建物.obj');
  await page.screenshot({path:'test-results/image-to-3d.png',fullPage:true});
  await page.locator('#imageUnfold').click();await expect(page.getByRole('tab',{name:'3Dモデル',exact:true})).toHaveAttribute('aria-selected','true');
  await expect(page.locator('#meshPreview')).toBeVisible();await expect(page.locator('#meshResults')).toContainText('三角形 12');
  expect(errors).toEqual([]);
});
test('locked AI does not send the selected image for generation',async({page})=>{
  let calls=0;await mockImages(page);await page.route('**/api/image-model/generate',r=>{calls++;return r.fulfill({json:model});});
  await page.goto('/#image3d');await select(page);await page.locator('#imageConsent').check();await page.locator('#imageGenerate').click();
  await expect(page.locator('#imageMessage')).toContainText('AI設定でプロファイルを解除');expect(calls).toBe(0);
});
test('changed size rejects old generated results and mobile layout stays within the screen',async({page})=>{
  let finish;await mockImages(page);await page.route('**/api/image-model/generate',async r=>{await new Promise(resolve=>{finish=resolve;});await r.fulfill({json:model});});
  await page.setViewportSize({width:390,height:844});await ai(page);await select(page);await page.locator('#imageConsent').check();await page.locator('#imageGenerate').click();
  await expect.poll(()=>Boolean(finish)).toBe(true);await page.locator('#imageHeight').fill('80');
  const response=page.waitForResponse(r=>r.url().endsWith('/api/image-model/generate'));finish();await response;
  await expect(page.locator('#imageObj')).toBeDisabled();await expect(page.locator('#imageModelInfo')).toBeHidden();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({path:'test-results/image-to-3d-mobile.png',fullPage:true});
});
