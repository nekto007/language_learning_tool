const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../app/static/js/grammar/practice.js'),'utf8');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
async function practice(options={}) {
  const nodes={},events={},storage=options.storage || new Map(),timers=[],calls=[];
  const element=id=>({id,style:{},disabled:false,value:'',type:'text',textContent:'',innerHTML:'Проверить',listeners:{},children:[],classList:{add(){},remove(){}},
    replaceChildren(...children){this.children=children;this.innerHTML='';},append(...children){this.children.push(...children);},
    addEventListener(name,fn){this.listeners[name]=fn;},focus(){},removeAttribute(){},
    querySelector(){return el('correct-label');},querySelectorAll(){return[];},click(){return this.listeners.click?.call(this);}});
  const el=id=>nodes[id] ||= element(id);
  for(const id of ['start-btn','check-btn','next-btn','dispute-btn','dispute-status','feedback-area','question-area'])el(id);
  el('dispute-btn').style.display='none';el('dispute-status').style.display='none';
  const first=options.matching?{id:41,exercise_type:'matching',pairs:[{left:'a',right:'b'}]}:{id:41,exercise_type:'fill_blank',question:'She ___ here.'};
  const context={exercises:[first,{id:42,exercise_type:'fill_blank',question:'I ___ here.'}],exerciseRevisions:options.revisions || {41:'first',42:'second'},topicId:4,sessionId:'session-one',
    document:{getElementById:el,createElement:element,querySelector:selector=>selector.includes('csrf')?{getAttribute:()=> 'csrf-token'}:selector.includes('llt-account-id')?{content:options.actor || '1'}:{value:'1'},querySelectorAll:()=>[],addEventListener:(name,fn)=>{events['document:'+name]=fn;}},
    window:{addEventListener:(name,fn)=>{events[name]=fn;}},sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
    setTimeout:(fn,delay)=>{const t={fn,delay};timers.push(t);return t;},clearTimeout:t=>{const i=timers.indexOf(t);if(i>=0)timers.splice(i,1);},AbortController,
    console:{error(){}},alert:message=>{throw Error(message);},
    fetch:async(url,init)=>{const call={url,init,body:JSON.parse(init.body)};calls.push(call);
      if(url.endsWith('/dispute'))return options.dispute?options.dispute(call):{ok:true,status:200,json:async()=>({success:true})};
      return options.submit?options.submit(call):{ok:true,status:200,json:async()=>({is_correct:options.correct??false,correct_answer:'is',dispute_token:options.token===undefined?'signed-dispute':options.token})};}
  };
  vm.createContext(context);vm.runInContext(source,context);
  events['document:DOMContentLoaded']();
  if(!options.reload)el('start-btn').click();
  const answer=options.matching?{0:0}:'My typed ANSWER!';el('user-answer').value=options.matching?JSON.stringify(answer):answer;
  const submit=()=>el('check-btn').click();
  if(!options.deferSubmit && !options.reload)await submit();
  return{nodes,el,events,storage,timers,calls,context,answer,submit,dispute:()=>el('dispute-btn').click()};
}
test('only a rejected response with a non-empty signed token offers a dispute',async()=>{
  const p=await practice();assert.equal(p.el('dispute-btn').style.display,'inline-flex');
  for(const options of [{correct:true},{token:null},{token:''},{token:123}]){
    const hidden=await practice(options);assert.equal(hidden.el('dispute-btn').style.display,'none');
  }
});
test('payload retains the original typed JSON, CSRF and cookie context; SRS continues normally',async()=>{
  for(const matching of [false,true]){
    const p=await practice({matching});p.el('user-answer').value='changed after feedback';await p.dispute();
    const call=p.calls.find(x=>x.url.endsWith('/dispute'));assert.deepEqual(call.body,{dispute_token:'signed-dispute',answer:p.answer});
    assert.equal(call.url,'/grammar-lab/api/exercise/41/dispute');assert.equal(call.init.credentials,'same-origin');assert.equal(call.init.headers['X-CSRFToken'],'csrf-token');
    assert.equal(p.el('dispute-status').textContent,'Ответ передан на проверку');assert.equal(p.el('dispute-btn').style.display,'none');
    p.el('next-btn').click();const saved=JSON.parse(p.storage.get('grammar_practice:1:4'));
    assert.equal(saved.currentIndex,1);assert.equal(saved.wrongCount,1);assert.equal(saved.correctCount,0);assert.equal(saved.totalXP,0);
    assert.match(p.el('question-area').innerHTML,/I ___ here/);assert.equal(p.calls.filter(x=>x.url.endsWith('/submit')).length,1);
  }
});
test('double click sends once and the independent Next button remains enabled',async()=>{
  let done;const wait=new Promise(resolve=>done=resolve);const p=await practice({dispute:()=>wait});
  const sending=p.dispute();await flush();await p.dispute();assert.equal(p.calls.filter(x=>x.url.endsWith('/dispute')).length,1);
  assert.equal(p.el('dispute-btn').disabled,true);assert(!p.el('next-btn').disabled);
  done({ok:true,status:200,json:async()=>({success:true})});await sending;
  assert.equal(p.el('dispute-status').textContent,'Ответ передан на проверку');
});
test('failed and malformed acknowledgments are retryable with the identical token and typed answer',async()=>{
  for(const fail of [()=>{throw Error('offline');},()=>({ok:false,status:503}),()=>({ok:true,status:200,json:async()=>({})})]){
    let count=0;const p=await practice({dispute:()=>++count===1?fail():{ok:true,status:200,json:async()=>({success:true})}});
    await p.dispute();assert.equal(p.el('dispute-btn').textContent,'Повторить запрос');assert.match(p.el('dispute-status').textContent,/Не удалось подтвердить/);
    await p.dispute();const calls=p.calls.filter(x=>x.url.endsWith('/dispute'));assert.deepEqual(calls[0].body,calls[1].body);
    assert.equal(p.el('dispute-status').textContent,'Ответ передан на проверку');
  }
});
test('next exercise aborts an old request and ignores a late success or failure',async()=>{
  for(const fail of [false,true]){
    let resolve,reject,signal;const wait=new Promise((r,j)=>{resolve=r;reject=j;});
    const p=await practice({dispute:call=>{signal=call.init.signal;return wait;}});const sending=p.dispute();await flush();
    p.el('next-btn').click();assert.equal(signal.aborted,true);
    if(fail)reject(Error('late'));else resolve({ok:true,status:200,json:async()=>({success:true})});await sending;
    assert.equal(p.el('dispute-status').style.display,'none');assert.equal(p.el('dispute-btn').style.display,'none');
    assert.equal(p.el('feedback-area').style.display,'none');assert.match(p.el('question-area').innerHTML,/I ___ here/);
  }
});
test('pagehide and changed session do not send or paint a stale dispute',async()=>{
  const hidden=await practice();hidden.events.pagehide({persisted:false});await hidden.dispute();assert.equal(hidden.calls.filter(x=>x.url.endsWith('/dispute')).length,0);
  const changed=await practice();changed.context.sessionId='session-two';await changed.dispute();assert.equal(changed.calls.filter(x=>x.url.endsWith('/dispute')).length,0);assert.equal(changed.el('dispute-btn').style.display,'none');
});
test('leaving the document discards a late submit response',async()=>{
  let done;const pending=new Promise(resolve=>done=resolve);const p=await practice({deferSubmit:true,submit:()=>pending});
  const sending=p.submit();p.events.pagehide({persisted:false});done({ok:true,status:200,json:async()=>({is_correct:false,correct_answer:'is',dispute_token:'stale-token'})});await sending;
  assert.equal(p.el('dispute-btn').style.display,'none');assert.equal(p.el('feedback-area').style.display,'none');
  assert.equal(JSON.parse(p.storage.get('grammar_practice:1:4')).wrongCount,0);
});
test('expired credentials or material require refresh rather than blind retries',async()=>{
  for(const status of [401,403,409]){
    const p=await practice({dispute:()=>({ok:false,status})});await p.dispute();assert.equal(p.el('dispute-btn').style.display,'none');assert.match(p.el('dispute-status').textContent,/Обновите страницу/);
  }
});
test('timeout restores retry without disabling normal SRS continuation',async()=>{
  const p=await practice({dispute:call=>new Promise((_r,reject)=>call.init.signal.addEventListener('abort',()=>reject(Error('timeout'))))});
  const sending=p.dispute();await flush();p.timers.find(t=>t.delay===15000).fn();await sending;
  assert.equal(p.el('dispute-btn').textContent,'Повторить запрос');assert.equal(p.el('dispute-btn').disabled,false);assert(!p.el('next-btn').disabled);
});

test('reload restores the confirmed feedback, explanation and acknowledged dispute without grading twice', async () => {
  const explanation = 'Сравните <woman> и women.';
  const submit = () => ({ok:true, json:async () => ({
    is_correct:false, correct_answer:'women', explanation, dispute_token:'signed-answer'
  })});
  const first = await practice({submit});
  await first.dispute();
  const restored = await practice({reload:true, storage:first.storage, correct:true});
  assert.equal(restored.el('check-btn').style.display, 'none');
  assert(restored.el('feedback-area').children.some(child => child.textContent === explanation));
  assert.equal(restored.el('progress-text').textContent, '1 / 2');
  assert.equal(restored.el('dispute-status').textContent, 'Ответ передан на проверку');
  await restored.submit();
  await restored.dispute();
  assert.equal(restored.calls.length, 0);
  restored.el('next-btn').click();
  restored.el('next-btn').click();
  assert.match(restored.el('question-area').innerHTML, /I ___ here/);
  await restored.submit();
  assert.equal(restored.el('next-label').textContent, 'Посмотреть результат');
  restored.el('next-btn').click();
  assert.equal(restored.el('correct-count').textContent, 1);
  assert.equal(restored.el('wrong-count').textContent, 1);
  assert.equal(restored.storage.size, 0);
});

test('a different account or changed exercise cannot restore a checked answer', async () => {
  const first = await practice();
  const other = await practice({reload:true, storage:first.storage, actor:'2'});
  assert.equal(other.el('exercise-screen').style.display, undefined);
  assert.equal(first.storage.size, 1);
  const changed = await practice({reload:true, storage:first.storage, revisions:{41:'updated',42:'second'}});
  assert.equal(changed.el('exercise-screen').style.display, undefined);
  assert.equal(first.storage.size, 0);
});

test('storage access failure does not convert a confirmed grade into a retry', async () => {
  const denied = () => { throw Error('storage disabled'); };
  const p = await practice({storage:{get:denied, set:denied, delete:denied}});
  assert.equal(p.el('feedback-area').style.display, 'block');
  assert.equal(p.el('check-btn').style.display, 'none');
  await p.submit();
  assert.equal(p.calls.length, 1);
});

test('a pending grade can finish after the same document returns from the back-forward cache', async () => {
  let resolve;
  const pending = new Promise(r => { resolve = r; });
  const p = await practice({deferSubmit:true, submit:() => pending});
  const sending = p.submit();
  p.events.pagehide({persisted:true});
  p.events.pageshow({persisted:true});
  resolve({ok:true, json:async () => ({is_correct:true})});
  await sending;
  assert.equal(p.el('check-btn').style.display, 'none');
  assert.equal(p.el('progress-text').textContent, '1 / 2');
});

test('an incomplete grading response never increments the attempts displayed to the learner', async () => {
  const p = await practice({submit:() => ({ok:true, json:async () => ({})})});
  assert.equal(p.el('check-btn').disabled, false);
  assert.equal(p.el('progress-text').textContent, '0 / 2');
});
