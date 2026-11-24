const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {readFileSync} = require('node:fs');
function setup() {
    const nodes = new Map();
    function element() {
        const classes = new Set();
        return {style:{}, dataset:{}, textContent:'', children:[], disabled:false,
            classList:{add:x=>classes.add(x), remove:x=>classes.delete(x), contains:x=>classes.has(x)},
            replaceChildren(){this.children=[]}, appendChild(x){this.children.push(x)}, focus(){this.focused=true},
        };
    }
    const ids = ['translationPopup','popupWord','popupTranslation','popupActions','popupStatus'];
    ids.forEach(id=>nodes.set(id,element()));
    const requests=[];
    const document={getElementById:id=>nodes.get(id), createElement:element, addEventListener(){},
        querySelector:()=>nodes.get('popupActions').children.find(x=>x.dataset.action==='add-to-learning')};
    const context=vm.createContext({document,window:{location:{href:'https://example.invalid/books/1/read'},addEventListener(){}},URL,
        fetch:(url,body)=>new Promise(resolve=>requests.push({url,body,resolve})),
        Audio:class {play(){return Promise.resolve()} pause(){}},console});
    const source=readFileSync('app/templates/books/reader_simple.html','utf8');
    vm.runInContext(source.slice(source.indexOf('let wordPanelRevision ='),source.indexOf('\nmakeWordsClickable();')),context);
    const choose=word=>{const el=element();el.dataset.word=word;context.handleWordClick({stopPropagation(){},currentTarget:el});return el};
    const reply=async(index,data,ok=true)=>{requests[index].resolve({ok,json:async()=>data});await new Promise(setImmediate)};
    return {context,nodes,requests,choose,reply};
}
test('switching words and closing invalidate late dictionary responses',async()=>{
    const t=setup(), first=t.choose('school'); t.choose('book');
    assert.equal(first.classList.contains('word-clickable--selected'),false);
    await t.reply(0,{translation:'школа',id:1});
    assert.equal(t.nodes.get('popupWord').textContent,'book');
    assert.equal(t.nodes.get('popupTranslation').textContent,'Подбираем перевод…');
    t.context.hideTranslationPopup(); await t.reply(1,{translation:'книга',id:2});
    assert.equal(t.nodes.get('translationPopup').style.display,'none');
    assert.equal(t.nodes.get('popupActions').children.length,0);
});
test('one recording control, literal text and no action for unavailable dictionary ID',async()=>{
    const t=setup();t.choose('school');
    await t.reply(0,{translation:'<img src=x>',id:1,has_audio:true,audio_url:'/school.mp3'});
    assert.equal(t.nodes.get('popupTranslation').textContent,'<img src=x>');
    assert.deepEqual(t.nodes.get('popupActions').children.map(x=>x.textContent),['Послушать','+ Учить']);
    t.choose('unknown');await t.reply(1,{translation:'значение',has_audio:true,audio_url:'javascript:alert(1)'});
    assert.equal(t.nodes.get('popupActions').children.length,0);
});
test('save double-clicks deduplicate, failure allows retry, late save cannot overwrite another word',async()=>{
    const t=setup();t.choose('school');await t.reply(0,{translation:'школа',id:7});
    const button=t.nodes.get('popupActions').children[0];
    t.context.addToLearning(7,'school');t.context.addToLearning(7,'school');assert.equal(t.requests.length,2);
    assert.equal(JSON.parse(t.requests[1].body.body).word_id,7);
    await t.reply(1,{},false);assert.equal(button.disabled,false);
    t.context.addToLearning(7,'school');t.choose('book');
    await t.reply(3,{translation:'книга',id:8});await t.reply(2,{success:true});
    assert.equal(t.nodes.get('popupActions').children[0].textContent,'+ Учить');
    assert.equal(t.nodes.get('popupStatus').textContent,'');
});
