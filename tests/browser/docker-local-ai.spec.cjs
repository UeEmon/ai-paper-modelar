const {test,expect}=require('@playwright/test');
test('Docker default and reset keep model ID, fetch models and save the verified host endpoint',async({page})=>{
  await page.route('**/api/ai/local-config',r=>r.fulfill({json:{runtime:'docker',automatic_host_mapping:true,endpoints:{ollama:'http://host.docker.internal:11434',local_openai:'http://host.docker.internal:1234/v1'}}}));
  await page.route('**/api/ai/models',r=>{expect(r.request().headers()['x-ai-endpoint']).toBe('http://host.docker.internal:11434');return r.fulfill({json:{ok:true,endpoint:'http://host.docker.internal:11434',models:[{id:'gemma:latest',name:'Gemma'}]}});});
  await page.route('**/api/ai/test',r=>r.fulfill({json:{ok:true,endpoint:'http://host.docker.internal:11434'}}));
  await page.goto('/#settings');await page.locator('#aiName').fill('Docker利用');await page.locator('#aiPassword').fill('docker-passphrase');await page.locator('#aiCreate').click();
  await expect(page.locator('#aiMessage')).toContainText('作成しました');await page.locator('#aiProvider').selectOption('ollama');
  await expect(page.locator('#aiEndpoint')).toHaveValue('http://host.docker.internal:11434');
  await page.locator('#aiModel').fill('gemma:latest');await page.locator('#aiEndpoint').fill('http://localhost:1234/v1');
  await page.locator('#aiResetEndpoint').click();await expect(page.locator('#aiMessage')).toContainText('接続先を http://host.docker.internal:11434 に戻しました');
  await expect(page.locator('#aiModel')).toHaveValue('gemma:latest');
  await page.locator('#aiModels').click();await expect(page.locator('#aiModelsMessage')).toContainText('1件を取得');
  await page.locator('#aiSave').click();await expect(page.locator('#aiMessage')).toContainText('暗号化して保存しました');
  await page.reload();await page.locator('#aiProfile').selectOption({label:'Docker利用'});await page.locator('#aiPassword').fill('docker-passphrase');await page.locator('#aiUnlock').click();
  await expect(page.locator('#aiEndpoint')).toHaveValue('http://host.docker.internal:11434');
});
