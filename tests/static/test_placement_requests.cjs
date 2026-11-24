const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../app/static/js/onboarding/placement.js'),'utf8');
const flush=async()=>{for(let i=0;i<5;i++)await new Promise(resolve=>setImmediate(resolve));};
const clean=value=>JSON.parse(JSON.stringify(value));
function attempt(simple=true,answered=0){return {id:'attempt-one',mode:'quick',scope:simple?'starter':'full',status:'active',answered,
 max_questions:14,question_count:simple?10:14,question:{id:'q'+(answered+1),input:'choice',prompt:'Choose the word '+(answered+1),skill_title:'Грамматика',options:['First answer','Second answer'],draft:''}};}
function harness(options={}){
 const nodes={},events={},calls=[],timers=new Map(),storage=options.storage||new Map();let timerId=0;
 function element(id){return {id,dataset:{},hidden:false,disabled:false,style:{},value:'',checked:false,textContent:'',children:[],listeners:{},attrs:{},
  setAttribute(name,value){this.attrs[name]=value;},removeAttribute(name){delete this.attrs[name];},
  addEventListener(name,fn){this.listeners[name]=fn;},append(...children){this.children.push(...children);},appendChild(child){this.children.push(child);},replaceChildren(...children){this.children=[...children];},
  querySelector:selector=>el(selector),querySelectorAll:selector=>[],focus(){},scrollIntoView(){},pause(){},load(){},play:()=>Promise.resolve(),
  showModal(){this.open=true;},close(){this.open=false;},click(){if(!this.disabled)return this.listeners.click?.call(this);}};}
 function el(id){return nodes[id]||=(element(id));}
 const root=el('placement-root');root.dataset={api:'/onboarding/placement/v2',account:'guest-one',guest:'true',simple:String(options.compact!==false),forceStart:'false',continueAfterApply:'false',return:'/',learnReturn:'/dashboard'};
 const modes=[element('quick'),element('detailed')];modes[0].dataset.mode='quick';modes[1].dataset.mode='detailed';
 for(const id of ['placement-open-retry','placement-retry','placement-test','placement-result'])el(id).hidden=true;
 const radios=()=>el('placement-options-list').children.flatMap(label=>label.children.filter(child=>child.name==='placement-option'));
 root.querySelectorAll=selector=>selector.includes('data-placement-choice')?el('placement-options-list').children.filter(child=>child.dataset.placementChoice):[];
 const context={document:{getElementById:el,createElement:element,createTextNode:text=>({textContent:text}),
  querySelector:selector=>selector.includes('csrf')?{content:'csrf-test'}:selector.includes('placement-option')?radios().find(input=>input.checked):null,
  querySelectorAll:selector=>selector==='[data-mode]'?modes:selector.includes('placement-option')?radios():[],addEventListener:(name,fn)=>events[name]=fn},
  window:{location:{assign:url=>{context.destination=url;}},addEventListener:(name,fn)=>events[name]=fn,scrollTo(){}},
  location:{pathname:'/placement',search:options.compact===false?'?advanced=1':'?simple=1'},history:{replaceState(){}},URLSearchParams,AbortController,
  localStorage:{getItem:key=>{if(options.blockStorage)throw Error('Storage unavailable');return storage.get(key)||null;},
   setItem:(key,value)=>{if(options.blockStorage)throw Error('Storage unavailable');storage.set(key,value);},removeItem:key=>{if(options.blockStorage)throw Error('Storage unavailable');storage.delete(key);}},
  setTimeout:(fn,ms)=>{const id=++timerId;timers.set(id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id),
  fetch:(url,init)=>{const call={url,init,body:init.body?JSON.parse(init.body):undefined};calls.push(call);return options.fetch?options.fetch(call,calls.length):Promise.resolve(ok({available:true,active:attempt(options.compact!==false),latest:null}));}
 };
 vm.createContext(context);vm.runInContext(source,context);
 return {context,el,root,modes,calls,events,storage,timers,radios,
  timeout(){const timer=[...timers.values()].find(value=>value.ms===15000);assert.ok(timer,'A request deadline must be registered');timer.fn();},
  async choose(){if(options.compact!==false)el('placement-options-list').children[0].click();else{const input=radios()[0];input.checked=true;input.listeners.change();el('placement-answer').click();}await flush();}};
}
function ok(data){return {ok:true,status:200,json:async()=>({success:true,...data})};}
for(const compact of [true,false]){
 test(`${compact?'compact':'advanced'} hung fetch releases busy and offers opening retry`,async()=>{
  let late;const blocked=new Promise(resolve=>late=resolve);let count=0;
  const h=harness({compact,fetch:()=>++count===1?blocked:Promise.resolve(ok({available:true,active:attempt(compact),latest:null}))});
  await flush();assert.equal(h.root.attrs['aria-busy'],'true');h.timeout();await flush();
  assert.equal(h.root.attrs['aria-busy'],'false');assert.equal(h.el('placement-open-retry').hidden,false);assert.equal(h.el('placement-open-retry').disabled,false);assert.equal(h.calls[0].init.signal.aborted,true);
  h.el('placement-open-retry').click();await flush();assert.equal(h.el('placement-question-title').textContent,'Choose the word 1');
  late(ok({available:true,active:attempt(compact,8),latest:null}));await flush();assert.equal(h.el('placement-question-title').textContent,'Choose the word 1');
  assert.equal(h.calls.filter(call=>call.init.method==='POST').length,0);assert.equal(h.timers.size,0);
 });
 test(`${compact?'compact':'advanced'} hung response JSON also reaches the same deadline`,async()=>{
  const h=harness({compact,fetch:()=>Promise.resolve({ok:true,status:200,json:()=>new Promise(()=>{})})});await flush();h.timeout();await flush();
  assert.equal(h.root.attrs['aria-busy'],'false');assert.equal(h.el('placement-open-retry').hidden,false);assert.equal(h.timers.size,0);
 });
 test(`${compact?'compact':'advanced'} timed-out answer retries exact pending without accepting a late result`,async()=>{
  let done,answerCalls=0;const blocked=new Promise(resolve=>done=resolve);
  const h=harness({compact,fetch:call=>{if(call.url.endsWith('/answer'))return ++answerCalls===1?blocked:Promise.resolve(ok({attempt:attempt(compact,1)}));return Promise.resolve(ok({available:true,active:attempt(compact),latest:null}));}});
  await flush();await h.choose();const original=clean(h.calls.find(call=>call.url.endsWith('/answer')).body);h.timeout();await flush();
  assert.equal(h.el('placement-retry').hidden,false);assert.equal(h.el('placement-retry').disabled,false);assert.equal(h.root.attrs['aria-busy'],'false');
  assert.equal(h.el('placement-question-title').textContent,'Choose the word 1');assert.equal(h.el('placement-unknown').disabled,true);
  h.el('placement-retry').click();await flush();const posts=h.calls.filter(call=>call.url.endsWith('/answer'));assert.equal(posts.length,2);assert.deepEqual(posts[1].body,original);
  assert.equal(h.el('placement-question-title').textContent,'Choose the word 2');done(ok({attempt:attempt(compact,7)}));await flush();assert.equal(h.el('placement-question-title').textContent,'Choose the word 2');
 });
 test(`${compact?'compact':'advanced'} unavailable storage still posts and retries exact in-memory answer`,async()=>{
  let posts=0;const h=harness({compact,blockStorage:true,fetch:call=>{if(call.url.endsWith('/answer'))return ++posts===1?Promise.reject(Error('offline')):Promise.resolve(ok({attempt:attempt(compact,1)}));return Promise.resolve(ok({available:true,active:attempt(compact),latest:null}));}});
  await flush();await h.choose();assert.equal(posts,1,'Storage cannot block an otherwise usable guest attempt');
  assert.equal(h.el('placement-retry').hidden,false);assert.match(h.el('placement-status').textContent,/только в этой вкладке/);
  const original=clean(h.calls.find(call=>call.url.endsWith('/answer')).body);h.el('placement-retry').click();await flush();
  assert.equal(posts,2);assert.deepEqual(h.calls.filter(call=>call.url.endsWith('/answer'))[1].body,original);assert.equal(h.el('placement-question-title').textContent,'Choose the word 2');
  const next=harness({compact,blockStorage:true,fetch:()=>Promise.resolve(ok({available:true,active:attempt(compact,1),latest:null}))});await flush();
  assert.equal(next.calls.length,1);assert.match(next.calls[0].url,/\/status$/);assert.equal(next.el('placement-question-title').textContent,'Choose the word 2');
 });
 test(`${compact?'compact':'advanced'} unconfirmed HTTP200 cannot discard a pending answer`,async()=>{
  let posts=0;const h=harness({compact,fetch:call=>{if(call.url.endsWith('/answer'))return ++posts===1?Promise.resolve({ok:true,status:200,json:async()=>({})}):Promise.resolve(ok({attempt:attempt(compact,1)}));return Promise.resolve(ok({available:true,active:attempt(compact),latest:null}));}});
  await flush();await h.choose();assert.equal(h.el('placement-retry').hidden,false);assert.equal(h.el('placement-unknown').disabled,true);
  const original=clean(h.calls.find(call=>call.url.endsWith('/answer')).body);h.el('placement-retry').click();await flush();assert.equal(posts,2);
  assert.deepEqual(h.calls.filter(call=>call.url.endsWith('/answer'))[1].body,original);
 });
}
test('ordinary chooser first GET failure has a visible existing retry before enabling 14/24 mode buttons',async()=>{
 let calls=0;const h=harness({compact:false,fetch:()=>++calls===1?Promise.reject(Error('offline')):Promise.resolve(ok({available:true,active:null,latest:null}))});await flush();
 assert.equal(h.el('placement-open-retry').hidden,false);assert.ok(h.modes.every(button=>button.disabled));h.el('placement-open-retry').click();await flush();
 assert.equal(h.el('placement-chooser').hidden,false);assert.ok(h.modes.every(button=>!button.disabled));assert.equal(h.root.attrs['aria-busy'],'false');
});
