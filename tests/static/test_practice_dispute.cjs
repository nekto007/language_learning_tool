const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname,'../../app/static/js/guided-practice.js'),'utf8');
const flush = () => new Promise(resolve=>setImmediate(resolve));

async function editor(options={}) {
  let document;
  class Element {
    constructor(tag) {this.tag=tag;this.children=[];this.dataset={};this.style={};this.attrs={};this.listeners={};this._text='';this.classList={add(){}};}
    get textContent(){return this._text+this.children.map(x=>x.textContent).join('');}
    set textContent(value){this._text=String(value);this.children=[];}
    append(...children){for(const child of children){child.parent=this;this.children.push(child);}}
    prepend(child){child.parent=this;this.children.unshift(child);}
    replaceChildren(...children){this.children=[];this.append(...children);}
    setAttribute(k,v){this.attrs[k]=v;}
    addEventListener(k,fn){this.listeners[k]=fn;}
    scrollIntoView(){}
    focus(){document.activeElement=this;}
    contains(element){return element===this || this.children.some(x=>x.contains(element));}
    get lastElementChild(){return this.children.at(-1);}
    get firstElementChild(){return this.children[0];}
    querySelectorAll(selector){
      const all=[];const walk=e=>{for(const child of e.children){all.push(child);walk(child);}};walk(this);
      return all.filter(e=>selector==='button'?e.tag==='button':selector==='h2'?e.tag==='h2':selector==='h3'?e.tag==='h3':selector==='[data-check]'?e.dataset.check:selector==='[role="status"]'?e.attrs.role==='status':false);
    }
    querySelector(selector){if(selector==='[role="status"] h3')return this.querySelector('[role="status"]')?.querySelector('h3');return this.querySelectorAll(selector)[0]||null;}
  }
  const root=new Element('main'), screen=new Element('section'),error=new Element('p'),warning=new Element('p'),note=new Element('p'),goal=new Element('p');
  root.dataset={account:'7',lesson:'42',endpoint:'/curriculum/api/lesson/42/practice',...(options.review?{reviewOnly:'true'}:{})};
  const refs={'#practice-screen':screen,'#practice-error':error,'#practice-storage-warning':warning,'#practice-draft-note':note,'#practice-goal':goal};
  root.append(screen);const query=root.querySelector.bind(root);root.querySelector=selector=>refs[selector]||query(selector);
  document={activeElement:null,getElementById:id=>id==='guided-practice'?root:null,querySelector:()=>({content:'csrf-test'}),createElement:tag=>new Element(tag),createTextNode:text=>{const e=new Element('#text');e.textContent=text;return e;}};
  const answer=options.answer??'My exact ANSWER!';
  const lesson={type:options.type||'quiz',quiz_phase:'first',content_revision:'r1',session_token:'signed-session',questions:[{id:'0',input:'text',instruction:'Write an answer',prompt:'A question',options:[]}],theory:[],support_mode:'off'};
  const draft={revision:'r1',lessonType:lesson.type,index:0,answers:{0:answer},first:{0:answer},checks:{0:{correct:!!options.correct,expected:'Another answer',explanation:'An explanation'}},help:{},fragments:{},levels:{},readSteps:[],intro:false,disputes:options.disputes||{}};
  const rows=new Map([['llt:practice:7:42:first',JSON.stringify(draft)]]);
  const storage={getItem:key=>rows.get(key)||null,setItem:(key,value)=>{if(options.quota)throw Error('quota');rows.set(key,value);},removeItem:key=>rows.delete(key)};
  const requests=[],timers=[];
  const fetch=async(url,init)=>{
    if(!url.endsWith('/dispute'))return {ok:true,status:200,json:async()=>({account_id:'7',lesson})};
    requests.push({url,init,body:JSON.parse(init.body)});
    return options.send ? options.send(requests.at(-1),requests.length) : {ok:true,status:200,json:async()=>({success:true})};
  };
  vm.runInNewContext(source,{document,window:{sessionStorage:storage,addEventListener(){},removeEventListener(){}},fetch,AbortController,setTimeout:fn=>{timers.push(fn);return fn;},clearTimeout:fn=>{const i=timers.indexOf(fn);if(i>=0)timers.splice(i,1);}});
  await flush();await flush();
  const buttons=()=>root.querySelectorAll('button');
  const click=async label=>{const el=buttons().find(x=>x.textContent===label);assert(el,'Missing button '+label);const result=el.listeners.click();await result;await flush();return el;};
  return {root,screen,error,warning,rows,requests,timers,buttons,click,draft};
}

test('quiz and grammar send the exact checked answer with CSRF, without changing its verdict',async()=>{
  for(const type of ['quiz','grammar']) {
    const p=await editor({type});await p.click('Мой ответ тоже верный');
    assert.equal(p.requests.length,1);const call=p.requests[0];
    assert.equal(call.url,'/curriculum/api/lesson/42/practice/dispute');
    assert.equal(call.init.credentials,'same-origin');assert.equal(call.init.headers['X-CSRFToken'],'csrf-test');
    assert.deepEqual(call.body,{session_token:'signed-session',question_id:'0',answer:'My exact ANSWER!'});
    assert.match(p.screen.textContent,/Ответ передан на проверку/);
    assert(!p.buttons().some(x=>x.dataset.dispute));assert(!p.buttons().find(x=>x.textContent==='Дальше').disabled);
    const saved=JSON.parse(p.rows.get('llt:practice:7:42:first'));
    assert.equal(saved.checks[0].correct,false);assert.deepEqual(saved.first,p.draft.first);assert.equal(saved.result,undefined);
  }
});
test('correct answers, finals, mini-review, other lesson types and empty answers have no dispute action',async()=>{
  for(const options of [{correct:true},{type:'final_test'},{review:true},{type:'reading'},{type:'shadow_reading'},{answer:''}]) {
    const p=await editor(options);assert(!p.buttons().some(x=>x.dataset.dispute));assert.equal(p.requests.length,0);
  }
});
test('double click sends once and exposes an in-flight status until acknowledged',async()=>{
  let release;const pending=new Promise(resolve=>release=resolve);
  const p=await editor({send:()=>pending});const old=p.buttons().find(x=>x.dataset.dispute);
  const first=old.listeners.click();await flush();await old.listeners.click();
  assert.equal(p.requests.length,1);assert.match(p.screen.textContent,/Передаём ответ/);
  assert(p.buttons().filter(x=>x.dataset.dispute).every(x=>x.disabled));
  release({ok:true,status:200,json:async()=>({success:true})});await first;assert.match(p.screen.textContent,/Ответ передан/);
});
test('network or malformed acknowledgments remain retryable and do not claim success',async()=>{
  for(const fail of [()=>{throw Error('offline');},()=>({ok:false,status:503,json:async()=>({success:false})}),()=>({ok:true,status:200,json:async()=>({})})]) {
    const p=await editor({send:(_request,count)=>count===1?fail():{ok:true,status:200,json:async()=>({success:true})}});
    await p.click('Мой ответ тоже верный');assert.match(p.screen.textContent,/Не удалось подтвердить/);assert(!p.screen.textContent.includes('Ответ передан на проверку'));
    await p.click('Повторить запрос');assert.equal(p.requests.length,2);assert.deepEqual(p.requests[0].body,p.requests[1].body);assert.match(p.screen.textContent,/Ответ передан/);
  }
});
test('a pending draft needs explicit retry; a sent draft does not send again or leak to another answer',async()=>{
  const pending=await editor({disputes:{0:{answer:'My exact ANSWER!',status:'pending'}}});
  assert.equal(pending.requests.length,0);assert.match(pending.screen.textContent,/Статус отправки неизвестен/);await pending.click('Повторить запрос');
  const sent=await editor({disputes:{0:{answer:'My exact ANSWER!',status:'sent'}}});assert.equal(sent.requests.length,0);assert(!sent.buttons().some(x=>x.dataset.dispute));
  const other=await editor({disputes:{0:{answer:'Previous answer',status:'sent'}}});assert(other.buttons().some(x=>x.textContent==='Мой ответ тоже верный'));
});
test('timeout is an unconfirmed submission, with retry and no permanent lesson lock',async()=>{
  const p=await editor({send:call=>new Promise((_resolve,reject)=>call.init.signal.addEventListener('abort',()=>reject(Error('timeout'))))});
  const send=p.buttons().find(x=>x.dataset.dispute).listeners.click();await flush();assert.equal(p.timers.length,1);p.timers[0]();await send;
  assert.match(p.screen.textContent,/Не удалось подтвердить/);assert(p.buttons().some(x=>x.textContent==='Повторить запрос'&&!x.disabled));
  assert(!p.buttons().find(x=>x.textContent==='Дальше').disabled);
});
test('changed material explains refresh; authentication failure removes the old editor',async()=>{
  const changed=await editor({send:()=>({ok:false,status:409,json:async()=>({success:false,error:'lesson_changed'})})});await changed.click('Мой ответ тоже верный');assert.match(changed.screen.textContent,/Обнови задание/);
  const expired=await editor({send:()=>({ok:false,status:401})});await expired.click('Мой ответ тоже верный');assert.equal(expired.screen.children.length,0);assert.match(expired.error.textContent,/Войди в аккаунт/);
});
test('failed draft writes do not suppress the acknowledged status in the live tab',async()=>{
  const p=await editor({quota:true});await p.click('Мой ответ тоже верный');assert.match(p.screen.textContent,/Ответ передан/);assert.equal(p.warning.hidden,false);
});
