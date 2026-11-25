const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../app/static/js/grammar/practice.js'),'utf8');
const restore=source.slice(source.indexOf('let restoreGeneration ='),source.indexOf('// Start button'));
const validator=source.slice(source.indexOf('function validPendingGrade('),source.indexOf('function showPendingGrade('));
const helperStart=source.indexOf('let restoredPracticeSessionId =');
const helper=helperStart<0?'':source.slice(helperStart,source.indexOf('function isCurrentExercise'));
const grade=source.slice(source.indexOf('function showCheckedExercise('),source.indexOf('function renderExercise('));
const renderable=source.slice(source.indexOf('function isRenderable('),source.indexOf('// Drop unactionable exercises'));
const revision='a'.repeat(64),key='grammar_practice:1:4',clean=value=>JSON.parse(JSON.stringify(value));
const items=[{id:17,question:'We ___ here.',exercise_type:'fill_blank',submission_id:'00000000-0000-4000-8000-000000000001'}];
function state(pending=false){return {exercises:items,revisions:{17:revision},sessionId:'saved-session',currentIndex:0,correctCount:0,wrongCount:0,totalXP:0,checkedAnswer:null,queueChanged:false,timestamp:Date.now(),pendingGrade:pending?{exerciseId:17,given:'are',body:{answer:'are',session_id:'saved-session',source:'topic_practice',exercise_revision:revision,submission_id:items[0].submission_id}}:null};}
function env(options={}){
 const storage=options.storage||new Map(options.state?[[key,JSON.stringify(options.state)]]:[]),nodes={},events={};let rendered=0;
 function node(id){return {id,style:{},hidden:false,disabled:false,textContent:'',children:[],classList:{add(){},remove(){}},listeners:{},
  setAttribute(){},querySelector:selector=>get(selector),addEventListener(name,fn){this.listeners[name]=fn;},replaceChildren(...children){this.children=children;},
  append(...children){for(const child of children){this.children.push(child);if(child&&child.id)nodes[child.id]=child;}},appendChild(child){this.append(child);}};}
 const missing=new Set(options.legacyDOM?['practice-resume-status','practice-resume-retry','practice-empty-link','next-label']:[]);
 function get(id){if(nodes[id])return nodes[id];if(missing.has(id))return null;return nodes[id]=node(id);}
 const context={practiceActor:'1',sessionKey:key,topicId:options.mixed?null:4,exercises:items,currentIndex:0,correctCount:0,wrongCount:0,totalXP:0,checkedAnswer:null,pendingGrade:null,pendingSaved:false,queueChanged:false,sessionRevisions:{},SUBMIT_TIMEOUT_MS:15000,
  document:{getElementById:get,createElement:()=>node(''),querySelector:()=>({content:'1'}),addEventListener:(name,fn)=>events[name]=fn},
  window:{location:{reload(){context.reload=true;}}},sessionStorage:{getItem:k=>storage.get(k)||null,removeItem:k=>storage.delete(k)},
  fetch:async()=>{throw Error('offline');},AbortController,setTimeout,clearTimeout,
  getCSRFToken:()=> 'csrf',showExercise(){rendered++;},
  clearSessionState:()=>storage.delete(key),saveSessionState:()=>{context.saved=true;},showSubmittedAnswer(){},renderDispute(){}};
 if(options.revisions!==false)context.exerciseRevisions={17:revision};
 vm.createContext(context);vm.runInContext("const sessionId = 'legacy-page-session';",context);
 vm.runInContext(helper+'\n'+validator+'\n'+renderable+'\n'+restore+'\n'+grade,context);
 return {context,storage,nodes,get,events,rendered:()=>rendered,run:code=>vm.runInContext(code,context),restore:()=>context.restoreSession(),init:()=>context.initializePractice()};
}
test('fill blank requires at least two underscores or an explicit source sentence', () => {
 const {isRenderable}=env().context;
 for (const [marker, expected] of [['__',true],['___',true],['_',false],['',false]]) {
  assert.equal(isRenderable({exercise_type:'fill_blank',question:`The vents ${marker} open.`}),expected);
 }
 assert.equal(isRenderable({exercise_type:'fill_blank',question:'Complete the sentence.',sentence:'The vents __ open.'}),true);
});
test('restoring a modern snapshot never writes the const sessionId emitted by legacy HTML',async()=>{
 const original=state(true),p=env({state:original});assert.equal(await p.restore(),true);assert.equal(p.rendered(),1);
 assert.equal(p.run('sessionId'),'legacy-page-session');assert.equal(p.run('currentPracticeSessionId()'),'saved-session');assert.deepEqual(clean(p.context.pendingGrade),original.pendingGrade);
});
test('legacy HTML without revision metadata stays usable and can reconcile a saved pending body',async()=>{
 const original=state(true),p=env({state:original,revisions:false,legacyDOM:true});assert.equal(await p.restore(),true);
 assert.equal(p.context.queueChanged,true);assert.deepEqual(clean(p.context.pendingGrade.body),original.pendingGrade.body);assert.equal(p.context.pendingSaved,true);
 const stale=env({state:state(false),revisions:false,legacyDOM:true});await stale.init();assert.equal(stale.get('start-btn').disabled,false);assert.equal(stale.storage.has(key),false);
});
test('a graded result uses the old Next button when there is no next-label span',()=>{
 const p=env({legacyDOM:true});assert.doesNotThrow(()=>p.context.showCheckedExercise(items[0],{correct:false,given:'is',expected:'are',explanation:'We + are.'}));
 assert.match(p.get('next-btn').textContent,/Посмотреть результат/);assert.equal(p.get('next-btn').style.display,'inline-flex');
});
test('legacy DOM gets a retry and safe exit if mixed resume encounters a network error',async()=>{
 const original=state(false);const p=env({state:original,legacyDOM:true,mixed:true,revisions:false});await p.init();
 assert.equal(p.get('start-btn').disabled,true);assert.ok(p.get('practice-resume-status'));assert.equal(p.get('practice-resume-retry').hidden,false);assert.ok(p.get('practice-resume-retry').listeners.click);
 assert.equal(p.get('practice-empty-link').hidden,false);assert.equal(p.storage.has(key),true);
});
test('new client does not import or overwrite the old unbound grammar cache key',async()=>{
 const storage=new Map([['grammar_practice_topic_4',JSON.stringify(state(false))]]),p=env({storage,legacyDOM:true,revisions:false});
 assert.equal(await p.restore(),false);assert.equal(p.rendered(),0);assert.equal(storage.has('grammar_practice_topic_4'),true);
});
