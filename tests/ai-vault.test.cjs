const {test}=require('node:test');
const assert=require('node:assert/strict');
const {webcrypto}=require('node:crypto');
const {AIVault,PREFIX}=require('../app/static/ai-vault.js');
class Storage {
  map=new Map();get length(){return this.map.size;}
  key(i){return [...this.map.keys()][i];}
  getItem(k){return this.map.get(k)??null;}
  setItem(k,v){this.map.set(k,v);}
  removeItem(k){this.map.delete(k);}
}
test('encrypted roundtrip, wrong password, provider and user isolation, lock and deletion',async()=>{
  const storage=new Storage(),v=new AIVault(storage,webcrypto);
  const alice=await v.create('Alice','alice-passphrase');
  await v.save('openai','custom-model','test-alice-key');
  await v.save('gemini','gemini-test','test-gemini-key');
  const serialized=JSON.stringify([...storage.map]);
  for(const secret of ['test-alice-key','test-gemini-key','alice-passphrase','custom-model'])assert.ok(!serialized.includes(secret));
  assert.ok(!JSON.stringify(v.key).includes('key_ops'));
  const first=JSON.parse(storage.getItem(PREFIX+alice));
  await v.save('openai','other-model','');
  assert.notEqual(JSON.parse(storage.getItem(PREFIX+alice)).iv,first.iv);
  assert.equal(v.headers()['X-AI-Key'],'test-alice-key');
  const bob=await v.create('Bob','bob-passphrase!');
  assert.deepEqual(v.headers(),{});
  await v.save('anthropic','claude-test','test-bob-key');
  v.lock();assert.deepEqual(v.headers(),{});
  await assert.rejects(v.unlock(alice,'wrong-password'));
  assert.deepEqual(v.headers(),{});
  await v.unlock(alice,'alice-passphrase');
  assert.equal(v.headers()['X-AI-Key'],'test-alice-key');
  await v.save('none','','');assert.deepEqual(v.headers(),{});
  assert.equal(new AIVault(storage,webcrypto).data,null);
  v.remove(alice);assert.deepEqual(v.list().map(p=>p.id),[bob]);
});
test('tampering and ciphertext copied between profiles cannot unlock',async()=>{
  const s=new Storage(),v=new AIVault(s,webcrypto);
  const id=await v.create('A','long-password!');await v.save('openai','test','test-secret');
  const record=s.getItem(PREFIX+id);s.setItem(PREFIX+'another',record);
  await assert.rejects(v.unlock('another','long-password!'));
  const broken=JSON.parse(record);broken.ciphertext='AAAA';s.setItem(PREFIX+id,JSON.stringify(broken));
  await assert.rejects(v.unlock(id,'long-password!'));
  assert.deepEqual(v.headers(),{});
});
test('storage denial, invalid data and lock during async work fail closed',async()=>{
  const s=new Storage(),v=new AIVault(s,webcrypto);
  await assert.rejects(v.create('A','short'));
  const pending=v.create('A','long-password!');v.lock();await assert.rejects(pending);
  assert.equal(s.length,0);
  const id=await v.create('A','long-password!');
  await assert.rejects(v.save('gemini','../../outside','test'));
  await assert.rejects(v.save('gemini','valid-model','bad\nkey'));
  const write=s.setItem;s.setItem=()=>{throw Error('storage unavailable');};
  await assert.rejects(v.save('openai','test','secret'));
  assert.deepEqual(v.headers(),{});s.setItem=write;
  await v.save('openai','test','secret');
  const save=v.save('openai','test','changed');v.lock();await assert.rejects(save);
  await v.unlock(id,'long-password!');assert.equal(v.headers()['X-AI-Key'],'secret');
});
