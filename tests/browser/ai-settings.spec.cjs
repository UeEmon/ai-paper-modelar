const {test,expect}=require('@playwright/test');
test.beforeEach(async({page})=>{await page.route('**/api/ai/test',r=>r.fulfill({json:{ok:true,message:'接続テストに成功しました。'}}));});
async function open(page){await page.goto('/');await page.getByRole('tab',{name:'AI設定',exact:true}).click();}
async function propose(page){
  await page.getByRole('tab',{name:'資料・AI提案',exact:true}).click();
  await page.locator('#plan').click();
  await expect(page.locator('#plan')).toBeEnabled();
  await page.getByRole('tab',{name:'AI設定',exact:true}).click();
}
async function create(page,name,password){
  await page.locator('#aiName').fill(name);await page.locator('#aiPassword').fill(password);
  await page.locator('#aiCreate').click();await expect(page.locator('#aiMessage')).toContainText('作成しました');
}
async function save(page,provider,model,key){
  await page.locator('#aiProvider').selectOption(provider);
  await page.locator('#aiModel').fill(model);await page.locator('#aiKey').fill(key);
  await page.locator('#aiSave').click();await expect(page.locator('#aiMessage')).toContainText('暗号化して保存しました');
}
test('profile lifecycle, encrypted reload, provider switching and proposal requests',async({page})=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const requests=[];
  await page.route('**/api/proposals',async route=>{
    requests.push(route.request());
    await route.fulfill({json:{provider:route.request().headers()['x-ai-provider']||'offline',proposals:[],notes:[]}});
  });
  await open(page);await create(page,'Alice','alice-passphrase');
  const alice=await page.locator('#aiProfile').inputValue();
  await save(page,'openai','custom-model','test-alice-key');
  await expect(page.locator('#aiKey')).toHaveValue('');
  await propose(page);await expect.poll(()=>requests.length).toBe(1);
  expect(requests[0].headers()['x-ai-key']).toBe('test-alice-key');
  expect(requests[0].postData()).not.toContain('test-alice-key');
  await save(page,'gemini','gemini-test','test-gemini-key');
  await page.locator('#aiProvider').selectOption('openai');
  await expect(page.locator('#aiModel')).toHaveValue('custom-model');
  await page.locator('#aiSave').click();await expect(page.locator('#aiState')).toContainText('openai');
  const storage=await page.evaluate(()=>JSON.stringify(localStorage));
  for(const secret of ['test-alice-key','test-gemini-key','alice-passphrase','custom-model'])expect(storage).not.toContain(secret);
  await page.reload();await page.getByRole('tab',{name:'AI設定',exact:true}).click();
  await expect(page.locator('#aiState')).toContainText('ロック中');
  await propose(page);await expect.poll(()=>requests.length).toBe(2);
  expect(requests[1].headers()['x-ai-key']).toBeUndefined();
  await page.locator('#aiProfile').selectOption(alice);
  await page.locator('#aiPassword').fill('wrong-passphrase');await page.locator('#aiUnlock').click();
  await expect(page.locator('#aiMessage')).toContainText('解除できません');
  await expect(page.locator('#aiPassword')).toHaveValue('');
  await page.locator('#aiPassword').fill('alice-passphrase');await page.locator('#aiUnlock').click();
  await expect(page.locator('#aiState')).toContainText('openai');
  await create(page,'Bob','bob-passphrase!');await save(page,'anthropic','claude-test','test-bob-key');
  await propose(page);await expect.poll(()=>requests.length).toBe(3);
  expect(requests[2].headers()['x-ai-key']).toBe('test-bob-key');
  await page.locator('#aiProfile').selectOption(alice);
  await expect(page.locator('#aiProvider')).toBeDisabled();
  await propose(page);await expect.poll(()=>requests.length).toBe(4);
  expect(requests[3].headers()['x-ai-key']).toBeUndefined();
  page.once('dialog',dialog=>dialog.accept());await page.locator('#aiDelete').click();
  await expect(page.locator('#aiProfile option')).toHaveCount(2);
  expect(errors).toEqual([]);
});
test('denied storage leaves offline proposals available',async({page})=>{
  await page.addInitScript(()=>Object.defineProperty(window,'localStorage',{get(){throw Error('denied');}}));
  await open(page);
  await expect(page.locator('#aiMessage')).toContainText('暗号化保存を利用できません');
  await propose(page);await expect(page.locator('#status')).toContainText('定型案');
});
test('other tab changes lock the active profile',async({page,context})=>{
  await open(page);await create(page,'Alice','alice-passphrase');await save(page,'openai','test','test-secret');
  const other=await context.newPage();await other.goto('/');
  await other.evaluate(()=>localStorage.clear());
  await expect(page.locator('#aiState')).toContainText('ロック中');
  await expect(page.locator('#aiKey')).toHaveValue('');
});
test('settings remain usable on a narrow screen',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  await open(page);await create(page,'モバイル利用者','mobile-passphrase');
  await save(page,'gemini','gemini-test','test-mobile-key');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({path:'test-results/ai-settings-mobile.png',fullPage:true});
});
test('local endpoint and vision settings are encrypted, restored and sent only to proposals',async({page})=>{
  const requests=[];
  await page.route('**/api/proposals',async route=>{
    requests.push(route.request());
    await route.fulfill({json:{provider:route.request().headers()['x-ai-provider']||'offline',proposals:[],notes:[]}});
  });
  await open(page);await create(page,'Local user','local-passphrase');
  const id=await page.locator('#aiProfile').inputValue();
  await page.locator('#aiProvider').selectOption('ollama');
  await expect(page.locator('#aiEndpoint')).toHaveValue('http://localhost:11434');
  await expect(page.locator('#aiVision')).not.toBeChecked();
  await page.locator('#aiEndpoint').fill('http://host.docker.internal:11434');
  await page.locator('#aiModel').fill('org/model:q4_K_M');
  await page.locator('#aiSave').click();await expect(page.locator('#aiMessage')).toContainText('暗号化して保存しました');
  await propose(page);await expect.poll(()=>requests.length).toBe(1);
  expect(requests[0].headers()['x-ai-key']).toBeUndefined();
  expect(requests[0].headers()['x-ai-endpoint']).toBe('http://host.docker.internal:11434');
  expect(requests[0].headers()['x-ai-vision']).toBe('false');
  expect(requests[0].postData()).not.toContain('host.docker.internal');
  const storage=await page.evaluate(()=>JSON.stringify(localStorage));
  expect(storage).not.toContain('host.docker.internal');expect(storage).not.toContain('org/model:q4_K_M');
  await page.locator('#aiProvider').selectOption('local_openai');
  await expect(page.locator('#aiEndpoint')).toHaveValue('http://localhost:1234/v1');
  await page.locator('#aiModel').fill('publisher/model');await page.locator('#aiVision').check();
  await page.locator('#aiSave').click();await expect(page.locator('#aiState')).toContainText('local_openai');
  await page.reload();await page.getByRole('tab',{name:'AI設定',exact:true}).click();
  await page.locator('#aiProfile').selectOption(id);await page.locator('#aiPassword').fill('local-passphrase');
  await page.locator('#aiUnlock').click();await expect(page.locator('#aiState')).toContainText('local_openai');
  await expect(page.locator('#aiVision')).toBeChecked();
  await propose(page);await expect.poll(()=>requests.length).toBe(2);
  expect(requests[1].headers()['x-ai-model']).toBe('publisher/model');
  expect(requests[1].headers()['x-ai-vision']).toBe('true');
  await page.locator('#aiProvider').selectOption('ollama');
  await expect(page.locator('#aiEndpoint')).toHaveValue('http://host.docker.internal:11434');
  await expect(page.locator('#aiVision')).not.toBeChecked();
  await page.locator('#aiProvider').selectOption('openai');
  await expect(page.locator('#aiLocal')).toBeHidden();
});
