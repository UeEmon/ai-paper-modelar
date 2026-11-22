const {test,expect}=require('@playwright/test');
const refs=[{title:'灯台の公式案内',url:'https://museum.example.org/lighthouse',summary:'円形の塔と灯室。',provider:'web',source_type:'Web検索の抜粋 (Bing)',query_match:true},{title:'灯台の概要',url:'https://ja.wikipedia.org/wiki/灯台',summary:'百科事典の概要。',provider:'wikipedia'}];
test('non-Wikipedia references display domain and search origin and reach AI with provenance',async({page})=>{
  let query,sent;
  await page.route('**/api/research?*',r=>{query=new URL(r.request().url()).searchParams;return r.fulfill({json:{results:refs,note:'抜粋のみ。',warnings:[]}});});
  await page.route('**/api/proposals',r=>{sent=r.request().postDataJSON();return r.fulfill({json:{provider:'ollama',proposals:[],notes:[]}});});
  await page.goto('/');await page.locator('#place').fill('灯台');await page.locator('#textSearch').click();
  await expect(page.locator('#research .reference')).toHaveCount(2);
  expect(query.get('scope')).toBe('all');
  await expect(page.locator('#research')).toContainText('museum.example.org');await expect(page.locator('#research')).toContainText('Web検索');
  await expect(page.locator('#research a').first()).toHaveAttribute('href',refs[0].url);
  await page.locator('#plan').click();await expect.poll(()=>sent?.sources?.length).toBe(1);
  expect(sent.sources[0]).toEqual({title:refs[0].title,url:refs[0].url,summary:refs[0].summary,source_type:refs[0].source_type});
});
test('scope changes clear old references and partial failures are explained',async({page})=>{
  const queries=[];
  await page.route('**/api/research?*',r=>{queries.push(new URL(r.request().url()).searchParams.get('scope'));return r.fulfill({json:{results:refs,note:'抜粋のみ。',warnings:['Web検索の一部を利用できませんでした。']}});});
  await page.goto('/');await page.locator('#textSearch').click();await expect(page.locator('#research .reference')).toHaveCount(2);
  await expect(page.locator('#research')).toContainText('一部を利用できません');
  await page.locator('#researchScope').selectOption('wikipedia');await expect(page.locator('#research .reference')).toHaveCount(0);
  await page.locator('#textSearch').click();await expect.poll(()=>queries.length).toBe(2);expect(queries).toEqual(['all','wikipedia']);
});
test('unrelated first candidates are not automatically selected',async({page})=>{
  await page.route('**/api/research?*',r=>r.fulfill({json:{results:[{...refs[0],query_match:false}],note:'抜粋のみ。'}}));
  await page.goto('/');await page.locator('#textSearch').click();await expect(page.locator('#researchState')).toContainText('0件をAIに使用');
  await expect(page.locator('#research .reference input')).not.toBeChecked();
});
