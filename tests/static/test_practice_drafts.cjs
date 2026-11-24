const {test} = require('node:test');
const assert = require('node:assert/strict');
const {Store,savedDraft} = require('../../app/static/js/practice-drafts.js');
const memory = () => {
  const rows = new Map();
  return {getItem:key=>rows.get(key)??null,setItem:(key,value)=>rows.set(key,value),removeItem:key=>rows.delete(key)};
};
function locks() {
  const held = new Set();
  return {request: async (name,options,action) => {
    assert.equal(options.ifAvailable,true);
    const lock = held.has(name) ? null : {name};
    if (lock) held.add(name);
    try { return await action(lock); } finally { if (lock) held.delete(name); }
  }};
}
const pause = () => new Promise(resolve=>setImmediate(resolve));
const view = (shared=memory(),lockManager=locks()) => ({localStorage:shared,sessionStorage:memory(),navigator:{locks:lockManager}});
const scope = 'llt:practice:1:2:';
const state = () => ({lessonType:'quiz',intro:false,index:1,answers:{0:'0',1:'unfinished'},first:{0:'0'},checks:{0:{correct:true}}});

test('closed-tab session is replaced while the scoped browser draft survives',async()=>{
  const first=view(), store=new Store(first,'1','2'); assert(await store.acquire());
  store.setItem(scope+'first',JSON.stringify(state())); store.setItem(scope+'active',scope+'first');
  store.close(); await pause();
  const next=view(first.localStorage,first.navigator.locks), resumed=new Store(next,'1','2');
  assert(await resumed.acquire()); assert.equal(resumed.durable,true);
  assert.deepEqual(JSON.parse(resumed.getItem(scope+'first')),state());
  assert.deepEqual(savedDraft(next,'1','2','quiz'),state()); resumed.close();
});
test('second tab cannot overwrite an editor; closing the owner releases its lock',async()=>{
  const first=view(), second=view(first.localStorage,first.navigator.locks);
  const a=new Store(first,1,2), b=new Store(second,1,2);
  assert(await a.acquire()); assert.equal(await b.acquire(),false);
  a.setItem(scope+'first','saved'); a.close(); await pause();
  assert(await b.acquire()); assert.equal(b.getItem(scope+'first'),'saved'); b.close();
});
test('late write and cleanup after close cannot overwrite or delete the new editor’s draft',async()=>{
  const page=view(),a=new Store(page,1,2),b=new Store(view(page.localStorage,page.navigator.locks),1,2);
  assert(await a.acquire()); a.setItem(scope+'first','old'); a.close(); await pause();
  assert(await b.acquire()); b.setItem(scope+'first','new');b.setItem(scope+'active',scope+'first');
  assert.throws(()=>a.setItem(scope+'first','late response'),/ownership/);
  assert.throws(()=>a.removeItem(scope+'first'),/ownership/);
  assert.throws(()=>a.removeItem(scope+'active'),/ownership/);
  assert.equal(b.getItem(scope+'first'),'new');assert.equal(b.getItem(scope+'active'),scope+'first');b.close();
});
test('a lock granted after pagehide cannot reopen the old editor’s write access',async()=>{
  let grant;
  const delayed={request:(_name,_options,action)=>new Promise(resolve=>{grant=()=>Promise.resolve(action({name:'delayed'})).then(resolve);})};
  const store=new Store(view(memory(),delayed),1,2),opening=store.acquire();
  store.close();grant();assert.equal(await opening,false);
  assert.throws(()=>store.setItem(scope+'first','late grant'),/ownership/);
});
test('accounts and lessons neither share a lock nor read each other’s draft',async()=>{
  const a=view(), first=new Store(a,1,2), other=new Store(view(a.localStorage,a.navigator.locks),3,2);
  assert(await first.acquire()); assert(await other.acquire());
  first.setItem(scope+'first','original'); assert.equal(other.getItem(scope+'first'),null);
  assert.throws(()=>other.setItem(scope+'first','overwrite'),/scope/);
  const forged=JSON.parse(a.localStorage.getItem(scope+'first'));
  a.localStorage.setItem(other.prefix+'first',JSON.stringify(forged));
  assert.equal(other.getItem(other.prefix+'first'),null);
  first.close();other.close();
});
test('pre-upgrade session drafts migrate and successful cleanup cannot resurrect them',async()=>{
  const page=view(), store=new Store(page,1,2);
  page.sessionStorage.setItem(scope+'first','legacy');
  assert(await store.acquire()); assert.equal(store.getItem(scope+'first'),'legacy');
  store.setItem(scope+'first','migrated'); assert.equal(page.sessionStorage.getItem(scope+'first'),null);
  store.removeItem(scope+'first'); assert.equal(store.getItem(scope+'first'),null); store.close();
});
test('absent, rejected or synchronously denied locks keep storage isolated to the tab',async()=>{
  for (const lockManager of [undefined,{request:()=>Promise.reject(Error('denied'))},{request:()=>{throw Error('denied');}}]) {
    const page=view(memory(),lockManager); if (!lockManager) page.navigator={};
    const store=new Store(page,1,2); assert(await store.acquire()); assert.equal(store.durable,false);
    store.setItem(scope+'first','tab only'); assert.equal(page.localStorage.getItem(scope+'first'),null);
    assert.equal(store.getItem(scope+'first'),'tab only');
  }
});
test('denied durable storage uses the existing tab; blocked session does not break healthy durable storage',async()=>{
  const blocked={getItem(){throw Error('denied');},setItem(){throw Error('denied');},removeItem(){throw Error('denied');}};
  const page=view(blocked), fallback=new Store(page,1,2);assert(await fallback.acquire());assert.equal(fallback.durable,false);
  fallback.setItem(scope+'first','safe');assert.equal(fallback.getItem(scope+'first'),'safe');fallback.close();
  const good=view();good.sessionStorage=blocked;const durable=new Store(good,1,2);assert(await durable.acquire());
  assert.equal(durable.getItem(scope+'first'),null);durable.setItem(scope+'first','safe');assert.equal(durable.getItem(scope+'first'),'safe');durable.removeItem(scope+'first');durable.close();
});
test('quota errors are visible to the editor and do not replace the saved draft',async()=>{
  const page=view(), store=new Store(page,1,2);assert(await store.acquire());
  store.setItem(scope+'first','original');page.localStorage.setItem=()=>{throw Error('quota');};
  assert.throws(()=>store.setItem(scope+'first','new'),/quota/);assert.equal(store.getItem(scope+'first'),'original');store.close();
});
test('malformed storage and completed or differently typed drafts do not promote resume',async()=>{
  const page=view(),store=new Store(page,1,2);assert(await store.acquire());
  store.setItem(scope+'active',scope+'first');
  for(const value of ['not json',JSON.stringify({...state(),result:{completed:true}}),JSON.stringify({...state(),lessonType:'final_test'})]) {
    store.setItem(scope+'first',value);assert.equal(savedDraft(page,1,2,'quiz'),null);
  }
  store.close();
});
