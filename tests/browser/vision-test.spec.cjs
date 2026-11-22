const {test,expect}=require('@playwright/test');
async function setup(page){
  await page.goto('/#settings');await page.locator('#aiName').fill('画像接続');await page.locator('#aiPassword').fill('vision-passphrase');
  await page.locator('#aiCreate').click();await expect(page.locator('#aiMessage')).toContainText('作成しました');
  await page.locator('#aiProvider').selectOption('ollama');await page.locator('#aiModel').fill('vision-model');
}
test('explicit image test and saving vision-enabled local models require verified image success',async({page})=>{
  let good=true,calls=0;
  await page.route('**/api/ai/test',r=>{calls++;expect(r.request().headers()['x-ai-test-mode']).toBe('image');return r.fulfill(good?{json:{ok:true,vision_tested:true}}:{status:422,json:{ok:false,vision_tested:false,message:'画像の内容を確認できませんでした。'}});});
  await setup(page);const before=await page.evaluate(()=>JSON.stringify(localStorage));
  await page.locator('#aiTestImage').click();await expect(page.locator('#aiMessage')).toContainText('画像入力と色の認識テストに成功');
  expect(await page.evaluate(()=>JSON.stringify(localStorage))).toBe(before);await expect(page.locator('#aiVision')).not.toBeChecked();
  good=false;await page.locator('#aiVision').check();await page.locator('#aiSave').click();await expect(page.locator('#aiMessage')).toContainText('画像の内容を確認できません');
  expect(await page.evaluate(()=>JSON.stringify(localStorage))).toBe(before);
  good=true;await page.locator('#aiSave').click();await expect(page.locator('#aiMessage')).toContainText('暗号化して保存しました');
  expect(calls).toBe(3);await expect(page.locator('#aiVision')).toBeChecked();
});
test('changing model while image test runs discards its result',async({page})=>{
  let finish;await page.route('**/api/ai/test',async r=>{await new Promise(resolve=>{finish=resolve;});await r.fulfill({json:{ok:true,vision_tested:true}});});
  await setup(page);await page.locator('#aiTestImage').click();await expect.poll(()=>Boolean(finish)).toBe(true);
  await page.locator('#aiModel').fill('other-model');finish();await expect(page.locator('#aiMessage')).toContainText('設定が変わったため');
  await expect(page.locator('#aiState')).toContainText('定型案');
});
