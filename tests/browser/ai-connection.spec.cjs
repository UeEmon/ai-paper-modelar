const {test,expect}=require('@playwright/test');
async function setup(page){
  await page.goto('/#settings');await page.locator('#aiName').fill('接続テスト用');
  await page.locator('#aiPassword').fill('connection-passphrase');await page.locator('#aiCreate').click();
  await expect(page.locator('#aiMessage')).toContainText('作成しました');
  await page.locator('#aiProvider').selectOption('ollama');await page.locator('#aiModel').fill('test-model');
}
test('test button does not save, failed verification keeps previous settings, save tests before activation',async({page})=>{
  let good=true,requests=0;
  await page.route('**/api/ai/test',r=>{requests++;expect(r.request().headers()['x-ai-model']).toBe('test-model');return r.fulfill(good?{json:{ok:true,message:'成功'}}:{status:400,json:{ok:false,message:'モデルが見つかりません。'}});});
  await setup(page);
  const original=await page.evaluate(()=>JSON.stringify(localStorage));
  await page.locator('#aiTest').click();await expect(page.locator('#aiMessage')).toContainText('接続テストに成功');
  expect(await page.evaluate(()=>JSON.stringify(localStorage))).toBe(original);
  await expect(page.locator('#aiState')).toContainText('定型案を使用');
  await expect(page.locator('#aiModel')).toHaveValue('test-model');
  good=false;await page.locator('#aiSave').click();await expect(page.locator('#aiMessage')).toContainText('モデルが見つかりません');
  expect(await page.evaluate(()=>JSON.stringify(localStorage))).toBe(original);
  await expect(page.locator('#aiState')).toContainText('定型案を使用');
  good=true;await page.locator('#aiSave').click();await expect(page.locator('#aiMessage')).toContainText('暗号化して保存しました');
  await expect(page.locator('#aiState')).toContainText('ollama を使用');expect(requests).toBe(3);
});
test('locking while a connection test is running prevents saving its result',async({page})=>{
  let finish;
  await page.route('**/api/ai/test',async r=>{await new Promise(resolve=>{finish=resolve;});await r.fulfill({json:{ok:true}});});
  await setup(page);const original=await page.evaluate(()=>JSON.stringify(localStorage));
  await page.locator('#aiSave').click();await expect(page.locator('#aiMessage')).toContainText('接続を確認しています');
  await expect.poll(()=>Boolean(finish)).toBe(true);
  await page.locator('#aiLock').click();finish();
  await expect(page.locator('#aiMessage')).toContainText('結果を破棄');
  await expect(page.locator('#aiState')).toContainText('ロック中');
  expect(await page.evaluate(()=>JSON.stringify(localStorage))).toBe(original);
});
