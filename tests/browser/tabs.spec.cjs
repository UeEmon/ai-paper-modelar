const {test,expect}=require('@playwright/test');
const tab=(page,name)=>page.getByRole('tab',{name,exact:true});
test('accessible tabs, keyboard and browser history preserve input and generated preview',async({page})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/');
  await expect(page.getByRole('tabpanel')).toHaveCount(1);
  await expect(tab(page,'資料・AI提案')).toHaveAttribute('aria-selected','true');
  await page.locator('#place').fill('タブで作る灯台');
  await page.locator('#fileSelect').setInputFiles({name:'reference.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aE0sAAAAASUVORK5CYII=','base64')});
  await tab(page,'基本形状').click();
  await expect(page.locator('#fileSelect')).toBeHidden();
  await page.locator('#template').selectOption('cylinder');
  await page.locator('#width').fill('2');await page.locator('#height').fill('5');
  await page.locator('#generate').click();
  await expect(page.locator('#drawing')).toBeVisible();
  await expect(page.locator('#savePdf')).toBeEnabled();
  const preview=await page.locator('#drawing').getAttribute('src');
  await tab(page,'AI設定').click();
  await expect(page.locator('#drawing')).toBeHidden();
  await page.locator('#aiName').fill('まだ保存していない名前');
  await tab(page,'基本形状').click();
  await expect(page.locator('#drawing')).toHaveAttribute('src',preview);
  await expect(page.locator('#width')).toHaveValue('2');
  await expect(page.locator('#workContext')).toContainText('タブで作る灯台');
  await page.goBack();await expect(tab(page,'AI設定')).toHaveAttribute('aria-selected','true');
  await expect(page.locator('#aiName')).toHaveValue('まだ保存していない名前');
  await page.goForward();await expect(tab(page,'基本形状')).toHaveAttribute('aria-selected','true');
  await tab(page,'基本形状').focus();await page.keyboard.press('ArrowRight');
  await expect(tab(page,'3Dモデル')).toBeFocused();await expect(page.locator('#meshFile')).toBeVisible();
  await page.keyboard.press('End');await expect(tab(page,'AI設定')).toBeFocused();
  await page.keyboard.press('Home');await expect(tab(page,'資料・AI提案')).toBeFocused();
  expect(await page.locator('#fileSelect').evaluate(input=>input.files[0].name)).toBe('reference.png');
  await page.keyboard.press('ArrowLeft');await expect(tab(page,'AI設定')).toBeFocused();
  expect(await page.locator('[role=tab][tabindex="0"]').count()).toBe(1);
  expect(errors).toEqual([]);
});
test('project changes apply across tabs and saved mesh opens its own tab',async({page})=>{
  await page.goto('/#projects');
  await page.locator('#projectTitle').fill('タブ連携テスト');await page.locator('#newProject').click();
  await expect(page.locator('#saveProject')).toBeEnabled();
  await expect(page.locator('#workContext')).toContainText('タブ連携テスト');
  const projectId=await page.locator('#projectSelect').inputValue();
  const mesh='v 0 0 0\nv 20 0 0\nv 0 20 0\nf 1 2 3\n';
  await page.request.post(`/api/projects/${projectId}/assets`,{multipart:{file:{name:'triangle.obj',mimeType:'application/octet-stream',buffer:Buffer.from(mesh)},view:'other'}});
  await page.reload();
  await expect(page.locator('#projectSelect')).toHaveValue(projectId);
  await tab(page,'資料・AI提案').click();
  await page.getByRole('button',{name:'この3Dモデルを展開',exact:true}).click();
  await expect(tab(page,'3Dモデル')).toHaveAttribute('aria-selected','true');
  await expect(page.locator('#meshPreview')).toBeVisible();
  await expect(page.locator('#meshResults')).toContainText('三角形 1');
  await tab(page,'基本形状').click();await tab(page,'3Dモデル').click();
  await expect(page.locator('#meshPreview')).toBeVisible();
});
test('mobile tabs stay visible without widening the page and links keep a single visible panel',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  await page.goto('/');
  for(const item of await page.getByRole('tab').all()){
    const box=await item.boundingBox();expect(box.x).toBeGreaterThanOrEqual(0);expect(box.x+box.width).toBeLessThanOrEqual(390);
  }
  await page.getByRole('button',{name:'基本形状の展開図へ進む →',exact:true}).click();
  await expect(tab(page,'基本形状')).toHaveAttribute('aria-selected','true');
  await page.screenshot({path:'test-results/tabs-mobile.png',fullPage:true});
  for(const name of ['3Dモデル','プロジェクト','AI設定','資料・AI提案']){
    await tab(page,name).click();
    await expect(page.getByRole('tabpanel')).toHaveCount(1);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  }
});
test('deep links and invalid hashes select valid panels',async({page})=>{
  await page.goto('/#mesh');await expect(page.locator('#meshFile')).toBeVisible();
  await page.reload();await expect(tab(page,'3Dモデル')).toHaveAttribute('aria-selected','true');
  await page.goto('/#unknown');await expect(tab(page,'資料・AI提案')).toHaveAttribute('aria-selected','true');
  await page.setViewportSize({width:1440,height:1050});
  await tab(page,'基本形状').click();
  await page.screenshot({path:'test-results/tabs-desktop.png',fullPage:true});
});
