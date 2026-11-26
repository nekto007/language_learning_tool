const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = ['practice-question-view.js', 'guided-practice.js']
  .map(file => fs.readFileSync(path.join(__dirname, '../../app/static/js', file), 'utf8')).join('\n');
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
      return all.filter(e=>selector==='[data-check]'?e.dataset.check:selector==='[role="status"]'?e.attrs.role==='status':e.tag===selector);
    }
    querySelector(selector){if(selector==='[role="status"] h3')return this.querySelector('[role="status"]')?.querySelector('h3');return this.querySelectorAll(selector)[0]||null;}
  }
  const root=new Element('main'), screen=new Element('section'),error=new Element('p'),warning=new Element('p'),note=new Element('p'),goal=new Element('p');
  root.dataset={account:options.account||'7',lesson:'42',endpoint:'/curriculum/api/lesson/42/practice',...(options.review?{reviewOnly:'true'}:{})};
  const refs={'#practice-screen':screen,'#practice-error':error,'#practice-storage-warning':warning,'#practice-draft-note':note,'#practice-goal':goal};
  const exit=new Element('a');exit.href='/dashboard';
  if(options.result||options.history) root.dataset.resultPlan='/api/daily-plan/next-step';
  root.append(exit,screen);const query=root.querySelector.bind(root);root.querySelector=selector=>refs[selector]||query(selector);
  document={activeElement:null,getElementById:id=>id==='guided-practice'?root:null,querySelector:()=>({content:'csrf-test'}),createElement:tag=>new Element(tag),createTextNode:text=>{const e=new Element('#text');e.textContent=text;return e;}};
  const answer=options.answer??'My exact ANSWER!';
  const lesson={type:options.type||'quiz',quiz_phase:options.correction?'correction':'first',content_revision:options.revision||'r1',session_token:'signed-session',questions:[{id:'0',input:'text',instruction:'Write an answer',prompt:'A question',options:[]}],theory:[],support_mode:'off'};
  if(options.correction) lesson.correction={attempt_id:'correction-id',first_score:50,previous_answers:{0:answer}};
  if(options.result||options.history) lesson.study_day='2026-11-24';
  const draft={revision:'r1',lessonType:lesson.type,index:options.result?1:0,answers:{0:answer},first:{0:answer},checks:{0:{correct:!!options.correct,expected:'Another answer',explanation:'An explanation'}},help:{},fragments:{},levels:{},readSteps:[],intro:false,disputes:options.disputes||{}};
  const key='llt:practice:'+root.dataset.account+':42:'+(lesson.correction?.attempt_id||'first');
  const rows=new Map(options.clean?[]:[[key,JSON.stringify(draft)]]);
  if(options.pending) {
    rows.set(key,JSON.stringify({...draft,pendingLesson:lesson,pendingSubmission:{session_token:'signed-session',answers:{0:answer}}}));
    rows.set('llt:practice:'+root.dataset.account+':42:active',key);
  }
  const storage={getItem:key=>rows.get(key)||null,setItem:(key,value)=>{if(options.quota)throw Error('quota');rows.set(key,value);},removeItem:key=>rows.delete(key)};
  const history=options.history&&{state:options.history,replaceState(next){this.state=next;}};
  const requests=[],planRequests=[],writes=[],identities=[],timers=[],events={};
  const fetch=async(url,init)=>{
    if(url.endsWith('/submit')) {
      writes.push(JSON.parse(init.body));
      return {ok:true,status:200,json:async()=>({success:true,lesson_id:42,...options.result})};
    }
    if(url.endsWith('?result_identity=1')) {
      identities.push(url);
      return {ok:true,status:200,json:async()=>({
        account_id:root.dataset.account,lesson:{id:42,type:lesson.type,content_revision:lesson.content_revision}
      })};
    }
    if(url.startsWith('/api/daily-plan/next-step?')) {
      planRequests.push(url);
      return {ok:true,status:200,json:async()=>({success:true,account_id:root.dataset.account,...await options.plan()})};
    }
    if(!url.endsWith('/dispute'))return {ok:true,status:200,json:async()=>({account_id:root.dataset.account,lesson})};
    requests.push({url,init,body:JSON.parse(init.body)});
    return options.send ? options.send(requests.at(-1),requests.length) : {ok:true,status:200,json:async()=>({success:true})};
  };
  vm.runInNewContext(source,{document,window:{history,sessionStorage:storage,addEventListener(k,fn){events[k]=fn;},removeEventListener(){}},fetch,AbortController,setTimeout:fn=>{timers.push(fn);return fn;},clearTimeout:fn=>{const i=timers.indexOf(fn);if(i>=0)timers.splice(i,1);}});
  await flush();await flush();
  const buttons=()=>root.querySelectorAll('button');
  const click=async label=>{const el=buttons().find(x=>x.textContent===label);assert(el,'Missing button '+label);const result=el.listeners.click();await result;await flush();return el;};
  return {root,screen,error,warning,rows,requests,timers,buttons,click,draft,planRequests,events,history,writes,identities};
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

test('result appears before plan lookup, links to same-lesson correction, and drops yesterday’s link on restore',async()=>{
  let resolve, planned=new Promise(done=>{resolve=done;});
  const p=await editor({result:{completed:false,correction_pending:true,score:50},plan:()=>planned});
  await p.click('Сохранить результат');
  assert.match(p.screen.textContent,/Результат первой попытки: 50%/);
  assert.match(p.screen.textContent,/В первой попытке были ошибки\./);
  assert.match(p.screen.textContent,/Уточняем следующий шаг/);
  assert.deepEqual(p.planRequests,['/api/daily-plan/next-step?result_day=2026-11-24']);
  resolve({status:'next',title:'Работа над ошибками',url:'/learn/42/?quiz_phase=correction',lesson_id:42,quiz_phase:'correction'});
  await flush();
  assert.deepEqual(p.screen.querySelectorAll('a').map(a=>[a.textContent,a.href]),[
    ['Работа над ошибками','/learn/42/?quiz_phase=correction'],['К плану дня','/dashboard']
  ]);
  planned=Promise.resolve({status:'day_changed'});
  await p.events.pageshow({persisted:true});await flush();
  assert.match(p.screen.textContent,/Начался новый учебный день/);
  assert.match(p.screen.textContent,/Результат первой попытки: 50%/);
  assert.match(p.screen.textContent,/В первой попытке были ошибки\./);
  assert.equal(p.screen.querySelectorAll('a').length,1);
});

test('restoring the first receipt leaves the correction link to the live plan', async () => {
  const result = {completed: false, correction_pending: true, score: 50};
  const first = await editor({history: {}, result, plan: () => ({status: 'next',
    title: 'Работа над ошибками', url: '/learn/42/?quiz_phase=correction', lesson_id: 42, quiz_phase: 'correction'})});
  await first.click('Сохранить результат');
  assert.equal(first.screen.querySelectorAll('a').length, 2);

  for (const plan of [() => ({status: 'secured'}), () => { throw Error('offline'); }]) {
    const restored = await editor({history: first.history.state, clean: true, plan});
    assert.match(restored.screen.textContent, /Результат первой попытки: 50%/);
    assert.match(restored.screen.textContent, /В первой попытке были ошибки\./);
    assert.doesNotMatch(restored.screen.textContent, /назначена отдельным заданием/);
    assert.deepEqual(restored.screen.querySelectorAll('a').map(a => a.textContent), ['К плану дня']);
    assert.equal(restored.writes.length, 0);
  }
});

test('review and failed results skip lookup; plan failure or a repeated lesson preserves the score and exit',async()=>{
  const scenarios=[
    [{review:true,result:{completed:true,score:100}},0,null],
    [{result:{completed:false,score:25}},0,null],
    [{result:{completed:true,score:100},plan:()=>{throw Error('offline');}},1,/Не удалось обновить план/],
    [{result:{completed:true,score:100},plan:()=>({status:'next',title:'Тот же урок',url:'/learn/42/?quiz_phase=correction',lesson_id:42,quiz_phase:'correction'})},1,null]
  ];
  for(const [options,lookups,copy] of scenarios) {
    const p=await editor(options);await p.click('Сохранить результат');
    assert.equal(p.planRequests.length,lookups);
    assert.match(p.screen.textContent,new RegExp(options.result.score+'%'));
    if(copy) assert.match(p.screen.textContent,copy);
    assert.deepEqual(p.screen.querySelectorAll('a').map(a=>a.textContent),['К плану дня']);
  }
});

test('a slow old lookup cannot replace a newer result state, and a changed account clears the result',async()=>{
  let finishOld;
  const old=new Promise(done=>{finishOld=done;});
  let planned=old;
  const p=await editor({result:{completed:true,score:100},plan:()=>planned});
  await p.click('Сохранить результат');
  planned=Promise.resolve({status:'paused'});
  await p.events.pageshow({persisted:true});
  finishOld({status:'next',title:'Устаревшее задание',url:'/learn/43/',lesson_id:43});
  await flush();
  assert.match(p.screen.textContent,/План на паузе/);
  assert.doesNotMatch(p.screen.textContent,/Устаревшее задание/);
  planned=Promise.resolve({status:'next',account_id:'8',title:'Чужое задание',url:'/learn/43/'});
  p.events.pageshow({persisted:true});await flush();
  assert.equal(p.screen.children.length,0);
  assert.match(p.error.textContent,/Аккаунт изменился/);
});

test('confirmed correction is restored only from its history entry, without storing answers or repeating submission',async()=>{
  const p=await editor({history:{anotherEntryField:7},correction:true,plan:()=>({status:'secured'}),
    result:{completed:true,score:50,correct_count:1,total_count:1,feedback:[{answer:'PRIVATE original'}]}});
  await p.click('Сохранить результат');
  const saved=p.history.state;
  assert.equal(saved.anotherEntryField,7);
  assert.doesNotMatch(JSON.stringify(saved),/PRIVATE|signed-session|My exact ANSWER!/);
  const restored=await editor({history:saved,clean:true,plan:()=>({status:'secured'})});
  assert.equal(restored.writes.length,0);
  assert.equal(restored.identities.length,1);
  assert.match(restored.screen.textContent,/Исправлено: 1 из 1. Исходный результат 50% сохранён/);
  assert.match(restored.screen.textContent,/План на сегодня выполнен/);

  for(const options of [{account:'8'},{revision:'r2'}]) {
    const other=await editor({history:saved,clean:true,...options});
    assert.equal(other.history.state.lltPracticeResult,undefined);
    assert.doesNotMatch(other.screen.textContent,/50%/);
    assert(other.buttons().some(button=>button.textContent==='К заданиям'));
    assert.equal(other.writes.length,0);
  }
  const direct=await editor({history:{},clean:true});
  assert.equal(direct.identities.length,0);
  assert(direct.buttons().some(button=>button.textContent==='К заданиям'));
});

test('a retry receipt can restore a result; explicit repeat clears that history entry',async()=>{
  const p=await editor({history:{},pending:true,plan:()=>({status:'plan'}),result:{completed:true,score:100}});
  assert.equal(p.writes.length,1);
  assert.equal(p.writes[0].session_token,'signed-session');
  assert.equal(p.history.state.lltPracticeResult.result.score,100);
  await p.click('Повторить урок');
  assert.equal(p.history.state.lltPracticeResult,undefined);
  assert.equal(p.writes.length,1);
  assert(p.buttons().some(button=>button.textContent==='К заданиям'));
});


test('an exam renders the whole part of the score and keeps its raw receipt',async()=>{
  const p=await editor({type:'final_test', result:{score:42.86,passed:false,completed:false,correct_count:3,total_count:7}});
  await p.click('Сохранить результат');
  assert.match(p.screen.textContent,/Результат теста: 42%/);
  assert.doesNotMatch(p.screen.textContent,/42[.,]86|Исправлено:/);
});
