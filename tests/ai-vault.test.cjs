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
test('local models, optional keys, endpoints and vision survive encryption independently of cloud settings',async()=>{
  const s=new Storage(),v=new AIVault(s,webcrypto);
  const id=await v.create('Local','local-passphrase');
  await v.save('openai','cloud-model','test-cloud-secret');
  await v.save('ollama','org/model:q4_K_M','',{endpoint:'http://localhost:11434/',vision:false});
  assert.deepEqual(v.headers(),{'X-AI-Provider':'ollama','X-AI-Model':'org/model:q4_K_M','X-AI-Endpoint':'http://localhost:11434','X-AI-Vision':'false'});
  await v.save('local_openai','publisher/model','test-local-secret',{endpoint:'http://localhost:1234/v1',vision:true});
  const record=s.getItem(PREFIX+id);
  for(const value of ['test-local-secret','localhost:1234','publisher/model','test-cloud-secret'])assert.ok(!record.includes(value));
  v.lock();await v.unlock(id,'local-passphrase');
  assert.equal(v.headers()['X-AI-Vision'],'true');
  assert.equal(v.headers()['X-AI-Key'],'test-local-secret');
  await v.save('openai','cloud-model','');
  assert.equal(v.headers()['X-AI-Key'],'test-cloud-secret');
  assert.equal(v.headers()['X-AI-Endpoint'],undefined);
  await assert.rejects(v.save('ollama','test','',{endpoint:'http://user:secret@localhost:11434'}));
  await assert.rejects(v.save('ollama','test','',{endpoint:'file:///tmp/test'}));
});
test('3D provider credentials stay encrypted and independent from simple AI settings',async()=>{
 const s=new Storage(),v=new AIVault(s,webcrypto);
 const alice=await v.create('3D user','three-d-passphrase');
 await v.save('openai','gpt-4.1-mini','test-text-key');
 await v.save3D('meshy','meshy-t2.5','test-meshy-key');
 await v.save3D('tripo','P1-20260311','test-tripo-key');
 await v.save3D('huggingface','TRELLIS.2','');
 assert.equal(v.headers()['X-AI-Key'],'test-text-key');
 assert.equal(v.headers3D()['X-3D-Provider'],'huggingface');
 for(const key of ['test-text-key','test-meshy-key','test-tripo-key'])assert.ok(!JSON.stringify([...s.map]).includes(key));
 v.lock();assert.deepEqual(v.headers3D(),{});
 await v.unlock(alice,'three-d-passphrase');
 await v.save3D('meshy','meshy-6','');assert.equal(v.headers3D()['X-3D-Key'],'test-meshy-key');
 await v.create('Other','other-passphrase');assert.deepEqual(v.headers3D(),{});
});
test('general text AI and simple 3D vision AI have independent providers, models and keys',async()=>{
 const s=new Storage(),v=new AIVault(s,webcrypto),id=await v.create('Separate AI','separate-passphrase');
 await v.save('openai','gpt-3.5-turbo','general-text-key');
 assert.deepEqual(v.headersSimple3D(),{});
 await assert.rejects(v.saveSimple3D('openai','gpt-4.1-mini','')); // never inherit general key
 await v.saveSimple3D('ollama','gemma4:12b','',{endpoint:'http://localhost:11434'});
 await v.save3D('meshy','meshy-t2.5','external-3d-key');
 assert.equal(v.headers()['X-AI-Model'],'gpt-3.5-turbo');
 assert.equal(v.headersSimple3D()['X-AI-Model'],'gemma4:12b');
 assert.equal(v.headersSimple3D()['X-AI-Vision'],'true');
 assert.equal(v.headers3D()['X-3D-Provider'],'meshy');
 await v.save('ollama','text-only','',{endpoint:'http://localhost:11434',vision:false});
 assert.equal(v.headersSimple3D()['X-AI-Model'],'gemma4:12b');
 await v.saveSimple3D('openai','gpt-4.1-mini','simple-only-key');
 assert.equal(v.headers()['X-AI-Model'],'text-only');
 for(const key of ['general-text-key','external-3d-key','simple-only-key'])assert.ok(!JSON.stringify([...s.map]).includes(key));
 v.lock();assert.deepEqual(v.headersSimple3D(),{});await v.unlock(id,'separate-passphrase');
 assert.equal(v.headersSimple3D()['X-AI-Key'],'simple-only-key');assert.equal(v.headers()['X-AI-Model'],'text-only');
 await v.create('Other user','different-passphrase');assert.deepEqual(v.headersSimple3D(),{});
});
