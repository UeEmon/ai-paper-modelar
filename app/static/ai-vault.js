"use strict";
/* No plaintext secrets, passphrases or decryption keys are persisted. */
(function(root){
  const PREFIX="paper-modelar-ai-v1:";
  const defaults={openai:"gpt-4.1-mini",gemini:"gemini-2.5-flash",anthropic:"claude-sonnet-4-5",ollama:"",local_openai:""};
  const endpoints={ollama:"http://localhost:11434",local_openai:"http://localhost:1234/v1"};
  const isLocal=provider=>Object.hasOwn(endpoints,provider);
  function validEndpoint(value){
    try{const url=new URL(value);return ["http:","https:"].includes(url.protocol)&&url.port&&!url.username&&!url.password&&!url.search&&!url.hash&&/^[!-~]{1,2048}$/.test(value);}
    catch{return false;}
  }
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
    prepare(provider,model,apiKey,options={},source=this.data){
      if(!source)throw Error("プロファイルを解除してください。");
      const data=structuredClone(source);
      if(provider!=="none"){
        const local=isLocal(provider);
        const pattern=local?/^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$/:/^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$/;
        if(!Object.hasOwn(defaults,provider)||!pattern.test(model))throw Error("モデルIDを確認してください。");
        const key=apiKey||data.providers[provider]?.apiKey||"";
        if((!local&&!key)||!/^[!-~]{0,512}$/.test(key))throw Error("APIキーを入力してください。");
        data.providers[provider]={model,apiKey:key};
        if(local){
          const endpoint=(options.endpoint||endpoints[provider]).replace(/\/+$/,"");
          if(!validEndpoint(endpoint))throw Error("ポート番号を含む接続先URLを確認してください。");
          data.providers[provider].endpoint=endpoint;
          data.providers[provider].vision=options.vision===true;
        }
      }
      data.provider=provider;return data;
    }
    async save(provider,model,apiKey,options={}){
      const epoch=this.epoch,id=this.id;
      const data=this.prepare(provider,model,apiKey,options);
      const old=JSON.parse(this.storage.getItem(PREFIX+id));
      const record=await this.encrypt(id,old.name,this.salt,this.key,data);
      if(epoch!==this.epoch)throw Error("操作が切り替わりました。");
      this.storage.setItem(PREFIX+id,JSON.stringify(record));this.data=data;
    }
    prepareSimple3D(provider,model,apiKey,options={}){
      if(!this.data)throw Error("プロファイルを解除してください。");
      const data=structuredClone(this.data);
      data.simple3D=this.prepare(provider,model,apiKey,{...options,vision:true},data.simple3D||{provider:"none",providers:{}});
      return data;
    }
    async saveSimple3D(provider,model,apiKey,options={}){
      const epoch=this.epoch,id=this.id,data=this.prepareSimple3D(provider,model,apiKey,options);
      const old=JSON.parse(this.storage.getItem(PREFIX+id));
      const record=await this.encrypt(id,old.name,this.salt,this.key,data);
      if(epoch!==this.epoch)throw Error("操作が切り替わりました。");
      this.storage.setItem(PREFIX+id,JSON.stringify(record));this.data=data;
    }
    headersSimple3D(data=this.data){return this.headers(data?.simple3D||null);}
    prepare3D(provider,model,apiKey){
      if(!this.data)throw Error("プロファイルを解除してください。");
      const data=structuredClone(this.data);
      if(!["huggingface","meshy","tripo"].includes(provider)||!/^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$/.test(model))throw Error("3Dモデルを選択してください。");
      const key=apiKey||data.threeD?.providers?.[provider]?.apiKey||"";
      if((provider!=="huggingface"&&!key)||!/^[!-~]{0,512}$/.test(key))throw Error("3D APIキーを入力してください。");
      data.threeD=data.threeD||{providers:{}};data.threeD.provider=provider;
      data.threeD.providers[provider]={model,apiKey:key};return data;
    }
    async save3D(provider,model,apiKey){
      const epoch=this.epoch,id=this.id,data=this.prepare3D(provider,model,apiKey);
      const old=JSON.parse(this.storage.getItem(PREFIX+id));
      const record=await this.encrypt(id,old.name,this.salt,this.key,data);
      if(epoch!==this.epoch)throw Error("操作が切り替わりました。");
      this.storage.setItem(PREFIX+id,JSON.stringify(record));this.data=data;
    }
    headers3D(data=this.data){
      const provider=data?.threeD?.provider,config=data?.threeD?.providers?.[provider];
      return config?{"X-3D-Provider":provider,"X-3D-Model":config.model,...(config.apiKey?{"X-3D-Key":config.apiKey}:{})}:{};
    }
    remove(id){this.lock();this.storage.removeItem(PREFIX+id);}
    headers(data=this.data){
      if(!data)return {};
      const provider=data.provider,config=data.providers[provider];
      if(provider==="none"||!config)return {};
      const headers={"X-AI-Provider":provider,"X-AI-Model":config.model};
      if(config.apiKey)headers["X-AI-Key"]=config.apiKey;
      if(isLocal(provider)){
        headers["X-AI-Endpoint"]=config.endpoint;
        headers["X-AI-Vision"]=config.vision?"true":"false";
      }
      return headers;
    }
  }
  root.PaperAIVault={AIVault,defaults,endpoints,isLocal,PREFIX};
  if(typeof module!=="undefined")module.exports=root.PaperAIVault;
})(globalThis);
