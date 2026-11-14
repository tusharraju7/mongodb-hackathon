import test from 'node:test';
import assert from 'node:assert/strict';
import {Backend,ApiError,normalizeBase} from '../src/api';
test('API sends bearer credentials and exact documented request body',async()=>{let seen: {url: string;init?:RequestInit}|undefined;const transport:typeof fetch=async(url,init)=>{seen={url:String(url),init};return Response.json({verdict:'pass',campaign:null,run_id:'run1'});};const api=new Backend('http://localhost:8000/','test-token',transport);await api.check({name:'Ad',product:'credit_card',offer_id:'offer1',region:'CA',channel:'social',language:'en',text:'Copy',save:false,use_memory:true,run_id:'run1'});assert.equal(seen?.url,'http://localhost:8000/compliance/check');assert.equal(new Headers(seen?.init?.headers).get('Authorization'),'Bearer test-token');assert.equal(JSON.parse(String(seen?.init?.body)).save,false);assert.equal(seen?.init?.redirect,'error');});
test('login sends email and password without a client-selected role',async()=>{let body:Record<string,unknown>={};const transport:typeof fetch=async(_,init)=>{body=JSON.parse(String(init?.body));return Response.json({token:'t',user:{role:'marketer'}});};await new Backend('http://localhost:8000','',transport).login('user@test.test','test');assert.deepEqual(Object.keys(body).sort(),['email','password']);});
test('uploads use multipart without manually setting its boundary',async()=>{const transport:typeof fetch=async(_,init)=>{assert.ok(init?.body instanceof FormData);assert.equal(new Headers(init?.headers).has('Content-Type'),false);assert.equal((init?.body as FormData).get('file') instanceof File,true);return Response.json({file_id:'asset1',type:'image'});};const result=await new Backend('http://localhost:8000','t',transport).upload(new File(['test'],'ad.png',{type:'image/png'}));assert.equal(result.file_id,'asset1');});
test('structured backend denial is surfaced, never treated as success',async()=>{const api=new Backend('http://localhost:8000','t',async()=>Response.json({error:'not_approvable',message:'Only passing ads can be approved.'},{status:409}));await assert.rejects(api.decision('id','approve','Reviewed'),e=>e instanceof ApiError&&e.status===409&&e.message==='Only passing ads can be approved.');});
test('expired login and provider rate limit retain their status',async()=>{for(const status of [401,429]){const api=new Backend('http://localhost:8000','t',async()=>Response.json({detail:'Try later'},{status}));await assert.rejects(api.campaigns(),e=>e instanceof ApiError&&e.status===status);}});
test('remote HTTP and credential-bearing addresses are rejected',()=>{assert.equal(normalizeBase('http://127.0.0.1:8000/'),'http://127.0.0.1:8000');assert.equal(normalizeBase('https://api.example.com'),'https://api.example.com');assert.throws(()=>normalizeBase('http://api.example.com'));assert.throws(()=>normalizeBase('https://secret:password@api.example.com'));assert.throws(()=>normalizeBase('javascript:alert(1)'));});
test('API paths cannot redirect credentials to another origin',async()=>{const api=new Backend('http://localhost:8000','t',async()=>{throw new Error('Must not fetch');});await assert.rejects(api.request('//example.com'));});


test('default transport never binds browser fetch to the Backend instance',async()=>{
  const original=globalThis.fetch;
  globalThis.fetch=async function(this: unknown){assert.ok(!(this instanceof Backend));return Response.json([]);};
  try {await new Backend('http://127.0.0.1:3000/api').campaigns();}
  finally {globalThis.fetch=original;}
});
