"use strict";
/* No plaintext secrets, passphrases or decryption keys are persisted. */
(function(root){
  const PREFIX="paper-modelar-ai-v1:";
  const defaults={openai:"gpt-4.1-mini",gemini:"gemini-2.5-flash",anthropic:"claude-sonnet-4-5"};
  const encode=new TextEncoder(), decode=new TextDecoder();
  const b64=bytes=>btoa(String.fromCharCode(...bytes));
  const bytes=value=>Uint8Array.from(atob(value),c=>c.charCodeAt(0));
  class AIVault {
    constructor(storage,cryptoAPI){this.storage=storage;this.crypto=cryptoAPI;this.lock();}
    lock(){this.epoch=(this.epoch||0)+1;this.id=null;this.key=null;this.salt=null;this.data=null;}
    list(){
      const result=[];
      for(let i=0;i<this.storage.length;i++){
        const key=this.storage.key(i);
        if(!key?.startsWith(PREFIX))continue;
        try{const item=JSON.parse(this.storage.getItem(key));
          if(item.version===1 && typeof item.name==="string")result.push({id:key.slice(PREFIX.length),name:item.name});
        }catch{/* damaged records do not prevent other profiles from opening */}
      }
      return result;
    }
    async derive(password,salt){
      const material=await this.crypto.subtle.importKey("raw",encode.encode(password),"PBKDF2",false,["deriveKey"]);
      return this.crypto.subtle.deriveKey({name:"PBKDF2",salt,iterations:600000,hash:"SHA-256"},material,
        {name:"AES-GCM",length:256},false,["encrypt","decrypt"]);
    }
    async create(name,password){
      this.lock();const epoch=this.epoch;
      if(!name.trim()||name.length>80||password.length<12)throw Error("名前と12文字以上のパスフレーズを入力してください。");
      const id=this.crypto.randomUUID(),salt=this.crypto.getRandomValues(new Uint8Array(16));
      const key=await this.derive(password,salt);
      const data={provider:"none",providers:{}};
      const record=await this.encrypt(id,name.trim(),salt,key,data);
      if(epoch!==this.epoch)throw Error("操作が切り替わりました。");
      this.storage.setItem(PREFIX+id,JSON.stringify(record));
      Object.assign(this,{id,salt,key,data});return id;
    }
    async unlock(id,password){
      this.lock();const epoch=this.epoch;
      try{
        const record=JSON.parse(this.storage.getItem(PREFIX+id));
        if(record.version!==1)throw Error();
        const salt=bytes(record.salt),key=await this.derive(password,salt);
        const raw=await this.crypto.subtle.decrypt({name:"AES-GCM",iv:bytes(record.iv),additionalData:encode.encode(id)},key,bytes(record.ciphertext));
        const data=JSON.parse(decode.decode(raw));
        if(!data.providers||!(data.provider==="none"||Object.hasOwn(defaults,data.provider)))throw Error();
        if(epoch!==this.epoch)throw Error();
        Object.assign(this,{id,key,salt,data});
      }catch{throw Error("解除できません。パスフレーズまたは保存データを確認してください。");}
    }
    async encrypt(id,name,salt,key,data){
      const iv=this.crypto.getRandomValues(new Uint8Array(12));
      const ciphertext=await this.crypto.subtle.encrypt({name:"AES-GCM",iv,additionalData:encode.encode(id)},key,encode.encode(JSON.stringify(data)));
      return {version:1,name,salt:b64(salt),iv:b64(iv),ciphertext:b64(new Uint8Array(ciphertext))};
    }
    async save(provider,model,apiKey){
      if(!this.data)throw Error("プロファイルを解除してください。");
      const epoch=this.epoch,id=this.id;
      const data=structuredClone(this.data);
      if(provider!=="none"){
        if(!Object.hasOwn(defaults,provider)||!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$/.test(model))throw Error("モデルIDを確認してください。");
        const key=apiKey||data.providers[provider]?.apiKey;
        if(!key||!/^[!-~]{1,512}$/.test(key))throw Error("APIキーを入力してください。");
        data.providers[provider]={model,apiKey:key};
      }
      data.provider=provider;
      const old=JSON.parse(this.storage.getItem(PREFIX+id));
      const record=await this.encrypt(id,old.name,this.salt,this.key,data);
      if(epoch!==this.epoch)throw Error("操作が切り替わりました。");
      this.storage.setItem(PREFIX+id,JSON.stringify(record));this.data=data;
    }
    remove(id){this.lock();this.storage.removeItem(PREFIX+id);}
    headers(){
      if(!this.data)return {};
      const provider=this.data.provider,config=this.data.providers[provider];
      if(provider==="none"||!config)return {};
      return {"X-AI-Provider":provider,"X-AI-Model":config.model,"X-AI-Key":config.apiKey};
    }
  }
  root.PaperAIVault={AIVault,defaults,PREFIX};
  if(typeof module!=="undefined")module.exports=root.PaperAIVault;
})(globalThis);
