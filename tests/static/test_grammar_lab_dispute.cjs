const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../app/static/js/grammar/practice.js'),'utf8');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
async function practice(options={}) {
  const nodes={},events={},storage=new Map(),timers=[],calls=[];
  const el=id=>nodes[id]||= {id,style:{},disabled:false,value:'',type:'text',textContent:'',innerHTML:'Проверить',listeners:{},classList:{add(){},remove(){}},
    addEventListener(name,fn){this.listeners[name]=fn;},focus(){},removeAttribute(){},
    querySelector(){return el('correct-label');},querySelectorAll(){return[];},click(){return this.listeners.click?.call(this);}};
  for(const id of ['start-btn','check-btn','next-btn','dispute-btn','dispute-status','feedback-area','question-area'])el(id);
  el('dispute-btn').style.display='none';el('dispute-status').style.display='none';
  const first=options.matching?{id:41,exercise_type:'matching',pairs:[{left:'a',right:'b'}]}:{id:41,exercise_type:'fill_blank',question:'She ___ here.'};
  const context={exercises:[first,{id:42,exercise_type:'fill_blank',question:'I ___ here.'}],topicId:4,sessionId:'session-one',
    document:{getElementById:el,querySelector:selector=>selector.includes('csrf')?{getAttribute:()=> 'csrf-token'}:{value:'1'},querySelectorAll:()=>[],addEventListener:(name,fn)=>{events['document:'+name]=fn;}},
    window:{addEventListener:(name,fn)=>{events[name]=fn;}},sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
    setTimeout:(fn,delay)=>{const t={fn,delay};timers.push(t);return t;},clearTimeout:t=>{const i=timers.indexOf(t);if(i>=0)timers.splice(i,1);},AbortController,
    console:{error(){}},alert:message=>{throw Error(message);},
    fetch:async(url,init)=>{const call={url,init,body:JSON.parse(init.body)};calls.push(call);
      if(url.endsWith('/dispute'))return options.dispute?options.dispute(call):{ok:true,status:200,json:async()=>({success:true})};
      return options.submit?options.submit(call):{ok:true,status:200,json:async()=>({is_correct:options.correct??false,correct_answer:'is',dispute_token:options.token===undefined?'signed-dispute':options.token})};}
  };
  vm.createContext(context);vm.runInContext(source,context);el('start-btn').click();
  const answer=options.matching?{0:0}:'My typed ANSWER!';el('user-answer').value=options.matching?JSON.stringify(answer):answer;
  const submit=()=>el('check-btn').click();
  if(!options.deferSubmit)await submit();
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
    p.el('next-btn').click();const saved=JSON.parse(p.storage.get('grammar_practice_topic_4'));
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
  const hidden=await practice();hidden.events.pagehide();await hidden.dispute();assert.equal(hidden.calls.filter(x=>x.url.endsWith('/dispute')).length,0);
  const changed=await practice();changed.context.sessionId='session-two';await changed.dispute();assert.equal(changed.calls.filter(x=>x.url.endsWith('/dispute')).length,0);assert.equal(changed.el('dispute-btn').style.display,'none');
});
test('late submit feedback cannot attach an old token or increment the new question counters',async()=>{
  let done;const pending=new Promise(resolve=>done=resolve);const p=await practice({deferSubmit:true,submit:()=>pending});
  const sending=p.submit();p.el('next-btn').click();done({ok:true,status:200,json:async()=>({is_correct:false,correct_answer:'is',dispute_token:'stale-token'})});await sending;
  assert.equal(p.el('dispute-btn').style.display,'none');assert.equal(p.el('feedback-area').style.display,'none');assert.match(p.el('question-area').innerHTML,/I ___ here/);
  assert.equal(JSON.parse(p.storage.get('grammar_practice_topic_4')).wrongCount,0);
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
