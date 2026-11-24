const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../app/static/js/grammar/practice.js'),'utf8');
const restore=source.slice(source.indexOf('let restoreGeneration ='),source.indexOf('// Start button'));
const sessionHelper=source.slice(source.indexOf('let restoredPracticeSessionId ='),source.indexOf('function isCurrentExercise'));
const validator=source.slice(source.indexOf('function validPendingGrade('),source.indexOf('function showPendingGrade('));
const clean=value=>JSON.parse(JSON.stringify(value));
const revision='a'.repeat(64),key='grammar_practice:1:srs';
const exercise=id=>({id,exercise_type:'fill_blank',question:'We ___ here.',submission_id:'00000000-0000-4000-8000-000000000001'});
function snapshot(extra={}){return {exercises:[exercise(17),exercise(18)],revisions:{17:revision,18:revision},sessionId:'saved-session',
 currentIndex:0,correctCount:0,wrongCount:0,totalXP:0,checkedAnswer:null,pendingGrade:null,queueChanged:false,timestamp:Date.now(),...extra};}
function pending(){return {exerciseId:17,given:'ARE!',body:{answer:'ARE!',session_id:'saved-session',source:'srs_review',
 exercise_revision:revision,submission_id:'00000000-0000-4000-8000-000000000001'}};}
function env(state,options={}){
 const stored=new Map(state?[[key,JSON.stringify(state)]]:[]),calls=[],shown=[],nodes={},events={},timers=new Set();
 let actor='1';
 const node=id=>nodes[id]||=( {style:{},hidden:false,disabled:false,textContent:'',listeners:{},
  addEventListener(name,fn){this.listeners[name]=fn;},querySelector(selector){return node(selector);}} );
 const response=options.response||{ok:true,status:200,json:async()=>({account_id:'1',session_id:'saved-session',
 exercises:state?.exercises.map(ex=>({...ex,submission_id:'00000000-0000-4000-8000-000000000099'})),exercise_revisions:state?.revisions})};
 const context={exercises:options.fresh||[],exerciseRevisions:options.revisions||{},topicId:options.topicId||null,sessionId:'new-session',
  practiceActor:'1',sessionKey:key,currentIndex:0,correctCount:0,wrongCount:0,totalXP:0,checkedAnswer:null,pendingGrade:null,pendingSaved:false,queueChanged:false,sessionRevisions:{},SUBMIT_TIMEOUT_MS:15000,
  document:{getElementById:node,querySelector:()=>({content:actor}),addEventListener:(name,fn)=>events[name]=fn},
  sessionStorage:{getItem:k=>stored.get(k)||null,removeItem:k=>stored.delete(k)},
  AbortController,setTimeout:fn=>{timers.add(fn);return fn;},clearTimeout:fn=>timers.delete(fn),
  getCSRFToken:()=> 'csrf-token',isRenderable:ex=>Boolean(ex&&ex.question),showExercise:i=>shown.push(i),
  fetch:async(url,init)=>{calls.push({url,init,body:JSON.parse(init.body)});return options.fetch?options.fetch():response;},
  clearSessionState:()=>stored.delete(key),saveSessionState:()=>{context.saved=true;},
 };
 vm.createContext(context);vm.runInContext(sessionHelper+'\n'+validator+'\n'+restore,context);
 return {context,stored,calls,shown,nodes,node,events,timers,actor:value=>actor=value,restore:()=>context.restoreSession(),init:()=>context.initializePractice()};
}
test('mixed reload hydrates the old ordered queue even when the fresh GET is empty or disjoint',async()=>{
 for(const fresh of [[],[exercise(99)]]){
  const state=snapshot(),p=env(state,{fresh});assert.equal(await p.restore(),true);
  assert.deepEqual(clean(p.context.exercises).map(ex=>ex.id),[17,18]);assert.equal(p.context.currentPracticeSessionId(),'saved-session');
  assert.equal(p.context.exercises[0].submission_id,state.exercises[0].submission_id);
  assert.deepEqual(clean(p.context.sessionRevisions),state.revisions);
  assert.deepEqual(p.shown,[0]);assert.equal(p.calls.length,1);
  assert.deepEqual(p.calls[0].body,{mode:'resume',account_id:'1',session_id:'saved-session',items:[{id:17,revision},{id:18,revision}]});
  assert.equal(p.calls[0].init.headers['X-CSRFToken'],'csrf-token');assert.equal(p.calls[0].init.credentials,'same-origin');assert.equal(p.timers.size,0);
 }
});
test('stale queue retains an exact pending body, including after the one-hour snapshot TTL',async()=>{
 const record=pending(),state=snapshot({pendingGrade:record,timestamp:Date.now()-7200000});
 const p=env(state,{response:{ok:false,status:409,json:async()=>({code:'lesson_changed'})}});
 assert.equal(await p.restore(),true);assert.deepEqual(clean(p.context.pendingGrade),record);
 assert.equal(p.context.pendingSaved,true);assert.equal(p.context.queueChanged,true);assert.equal(p.context.saved,true);
 assert.deepEqual(clean(p.context.sessionRevisions),state.revisions);assert.equal(p.stored.has(key),true);
});
test('confirmed stale replay with queueChanged survives another reload until explicit next',async()=>{
 const checked={correct:false,exerciseId:17,given:'ARE!',expected:'are'},state=snapshot({checkedAnswer:checked,wrongCount:1,queueChanged:true});
 const p=env(state,{response:{ok:false,status:409,json:async()=>({code:'lesson_changed'})}});
 assert.equal(await p.restore(),true);assert.deepEqual(clean(p.context.checkedAnswer),checked);assert.equal(p.context.queueChanged,true);
 assert.equal(p.context.pendingGrade,null);assert.equal(p.context.wrongCount,1);
});
test('stale draft without pending or confirmed reconciliation falls back to fresh selection',async()=>{
 const p=env(snapshot(),{fresh:[exercise(99)],response:{ok:false,status:409,json:async()=>({code:'lesson_changed'})}});
 assert.equal(await p.restore(),false);assert.equal(p.stored.has(key),false);assert.equal(p.context.exercises[0].id,99);assert.deepEqual(p.shown,[]);
});
test('network/auth/malformed resume cannot delete pending and offers a disabled-start retry',async()=>{
 for(const options of [{fetch:async()=>{throw Error('offline');}},
 {response:{ok:false,status:403,json:async()=>({error:'account_changed'})}},
 {response:{redirected:true}},
 {response:{ok:true,status:200,json:async()=>({account_id:'2',session_id:'saved-session',exercises:[]})}}]){
  const state=snapshot({pendingGrade:pending()}),p=env(state,options);await p.init();
  assert.deepEqual(JSON.parse(p.stored.get(key)),state);assert.equal(p.node('start-btn').disabled,true);
  assert.equal(p.node('practice-resume-retry').hidden,false);assert.match(p.node('practice-resume-status').textContent,/Не удалось|Сессия изменилась/);assert.deepEqual(p.shown,[]);
  assert.equal(p.node('practice-empty-link').hidden,false);
 }
});
test('a late resume after account/session changes does not apply the old queue',async()=>{
 for(const changed of ['actor','session']){
  let done;const response=new Promise(resolve=>done=resolve);const p=env(snapshot(),{fetch:()=>response});const task=p.restore();
  if(changed==='actor')p.actor('2');else p.context.sessionId='another-session';
  done({ok:true,status:200,json:async()=>({account_id:'1',session_id:'saved-session',exercises:[exercise(17),exercise(18)],exercise_revisions:{17:revision,18:revision}})});
  assert.equal(await task,null);assert.deepEqual(p.shown,[]);assert.equal(p.stored.has(key),true);
 }
});
test('topic restore remains synchronous before its first await and needs no resume HTTP',async()=>{
 const p=env(snapshot(),{topicId:4,revisions:{17:revision,18:revision}});const task=p.restore();
 assert.deepEqual(p.shown,[0]);assert.equal(p.calls.length,0);assert.equal(await task,true);
});
test('retired topic pending and later confirmed stale result survive an empty GET',async()=>{
 for(const state of [snapshot({pendingGrade:pending()}),snapshot({checkedAnswer:{correct:true,exerciseId:17,given:'are',expected:'are'},correctCount:1,queueChanged:true})]){
  if(state.pendingGrade)state.pendingGrade.body.source='topic_practice';
  const p=env(state,{topicId:4});assert.equal(await p.restore(),true);assert.equal(p.calls.length,0);assert.equal(p.context.queueChanged,true);
 }
});
test('empty no-cache bootstrap has an actionable empty state without sampling a new session',async()=>{
 const p=env(null);await p.init();assert.equal(p.calls.length,0);assert.equal(p.node('start-btn').disabled,true);
 assert.equal(p.node('practice-empty-link').hidden,false);assert.equal(p.node('.practice-start__title').textContent,'Нет доступных упражнений');
});
test('unsafe cached state is discarded without an unbounded resume request',async()=>{
 for(const state of [snapshot({exercises:Array.from({length:11},(_,i)=>exercise(i+1))}),snapshot({checkedAnswer:{correct:true,exerciseId:17,given:'are',expected:'are'},pendingGrade:pending()}),snapshot({timestamp:Date.now()+60000})]){
  const p=env(state);assert.equal(await p.restore(),false);assert.equal(p.calls.length,0);assert.equal(p.stored.has(key),false);
 }
});
test('legacy missing revisions falls back to fresh without a retry loop, while exact pending is retained',async()=>{
 const legacy=env(snapshot({revisions:{}}));assert.equal(await legacy.restore(),false);assert.equal(legacy.calls.length,0);
 const recovery=env(snapshot({revisions:{},pendingGrade:pending()}));assert.equal(await recovery.restore(),true);
 assert.equal(recovery.context.queueChanged,true);assert.deepEqual(clean(recovery.context.pendingGrade),pending());assert.equal(recovery.calls.length,0);
});
