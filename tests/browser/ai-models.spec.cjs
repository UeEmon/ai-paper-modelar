const {test,expect}=require('@playwright/test');
async function setup(page){
  await page.goto('/#settings');await page.locator('#aiName').fill('モデル選択');await page.locator('#aiPassword').fill('models-passphrase');
  await page.locator('#aiCreate').click();await expect(page.locator('#aiMessage')).toContainText('作成しました');
  await page.locator('#aiProvider').selectOption('ollama');
}
test('installed models can be selected and tested, saved, restored and used in proposals',async({page})=>{
  let tested,proposed;
  await page.route('**/api/ai/models',r=>r.fulfill({json:{ok:true,models:[{id:'org/model:q4',name:'Local chat'},{id:'gemma:latest',name:'Gemma'}]}}));
  await page.route('**/api/ai/test',r=>{tested=r.request().headers()['x-ai-model'];return r.fulfill({json:{ok:true}});});
  await page.route('**/api/proposals',r=>{proposed=r.request().headers()['x-ai-model'];return r.fulfill({json:{provider:'ollama',proposals:[],notes:[]}});});
  await setup(page);await page.locator('#aiModel').fill('');
  const before=await page.evaluate(()=>JSON.stringify(localStorage));
  await page.locator('#aiModels').click();await expect(page.locator('#aiModelsMessage')).toContainText('2件を取得');
  await page.locator('#aiModel').fill('invalid model?!');
  await page.locator('#aiModels').click();await expect(page.locator('#aiModelsMessage')).toContainText('2件を取得');
  expect(await page.evaluate(()=>JSON.stringify(localStorage))).toBe(before);
  await page.locator('#aiModelSelect').selectOption('org/model:q4');await expect(page.locator('#aiModel')).toHaveValue('org/model:q4');
  await page.locator('#aiSave').click();await expect(page.locator('#aiMessage')).toContainText('暗号化して保存しました');
  expect(tested).toBe('org/model:q4');const id=await page.locator('#aiProfile').inputValue();
  await page.reload();await page.locator('#aiProfile').selectOption(id);await page.locator('#aiPassword').fill('models-passphrase');
  await page.locator('#aiUnlock').click();await expect(page.locator('#aiModel')).toHaveValue('org/model:q4');
  await page.getByRole('tab',{name:'資料・AI提案',exact:true}).click();await page.locator('#plan').click();await expect.poll(()=>proposed).toBe('org/model:q4');
});
test('failed and empty catalogues preserve custom IDs and manual entry',async({page})=>{
  let empty=false;
  await page.route('**/api/ai/models',r=>r.fulfill(empty?{json:{ok:true,models:[]}}:{status:403,json:{ok:false,message:'一覧の閲覧権限がありません。'}}));
  await setup(page);await page.locator('#aiModel').fill('my-custom-model');
  await page.locator('#aiModels').click();await expect(page.locator('#aiModelsMessage')).toContainText('閲覧権限');
  await expect(page.locator('#aiModel')).toHaveValue('my-custom-model');
  empty=true;await page.locator('#aiModels').click();await expect(page.locator('#aiModelsMessage')).toContainText('モデルが見つかりません');
  await expect(page.locator('#aiModel')).toHaveValue('my-custom-model');await page.locator('#aiModel').fill('manual-model');
});
test('provider, endpoint and key changes clear prior catalogues and old responses',async({page})=>{
  let finish;
  await page.route('**/api/ai/models',async r=>{await new Promise(resolve=>{finish=resolve;});await r.fulfill({json:{ok:true,models:[{id:'old-provider-model',name:'Old'}]}}).catch(()=>{});});
  await setup(page);await page.locator('#aiModels').click();await expect.poll(()=>Boolean(finish)).toBe(true);
  await page.locator('#aiProvider').selectOption('local_openai');finish();
  await expect(page.locator('#aiModelSelect option')).toHaveCount(1);await expect(page.locator('#aiModelsMessage')).not.toContainText('1件を取得');
  await page.route('**/api/ai/models',r=>r.fulfill({json:{ok:true,models:[{id:'current-model',name:'Current'}]}}));
  await page.locator('#aiModels').click();await expect(page.locator('#aiModelSelect option')).toHaveCount(2);
  await page.locator('#aiEndpoint').fill('http://localhost:9999/v1');await expect(page.locator('#aiModelSelect option')).toHaveCount(1);
  await page.locator('#aiEndpoint').fill('http://localhost:1234/v1');await page.locator('#aiModels').click();await expect(page.locator('#aiModelSelect option')).toHaveCount(2);
  await page.locator('#aiKey').fill('new-test-key');await expect(page.locator('#aiModelSelect option')).toHaveCount(1);
});
