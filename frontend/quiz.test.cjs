const assert=require('node:assert/strict');
const fs=require('node:fs');const vm=require('node:vm');
class Element {
 constructor(tag){this.tag=tag;this.children=[];this.handlers={};this.attributes={};this.textContent='';this.value='';this.checked=false;this.hidden=false;this.disabled=false;}
 append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=nodes;}
 setAttribute(name,value){this.attributes[name]=value;}addEventListener(name,handler){this.handlers[name]=handler;}
}
const ctx={document:{createElement:tag=>new Element(tag)},console};
vm.runInNewContext(fs.readFileSync(__dirname+'/quiz.js','utf8'),ctx);
const walk=node=>[node,...node.children.flatMap(walk)];
const roles=(node,role)=>walk(node).filter(n=>n.attributes['data-quiz-role']===role);
const text=node=>walk(node).map(n=>n.textContent).join(' ');
const event=(id,item)=>({task_id:'t',type:'quiz.question.emitted',data:{position:id,item}});
const q=(id,type='single_choice')=>({id,type,question:'<script>Question?</script>',options:['<img src=x>','Two','Three'],answer_index:1,explanation:'DO NOT SHOW'});
(async()=>{
 const container=new Element('div'),calls=[];let pending=null;
 const request=async(path,options)=>{calls.push({path,options});if(pending)return pending;const id=Object.keys(options.answers)[0];return {feedback:[{item_id:id,status:'correct',explanation:'Server checked <b>answer</b>',correct_answer:1,score:1,max_score:1}]};};
 const quiz=ctx.TutorQuiz.create({container,request});quiz.beginTask({taskId:'t'});
 quiz.handleEvent(event(1,q('q1')));quiz.handleEvent(event(1,q('q1')));
 assert.equal(roles(container,'item').length,1);assert.ok(text(container).includes('<script>'));assert.ok(!text(container).includes('DO NOT SHOW'));
 let card=roles(container,'item')[0],controls=roles(card,'answer');controls[1].checked=true;
 await roles(card,'form')[0].handlers.submit({preventDefault(){}});
 assert.equal(calls[0].path,'/api/tasks/t/quiz/submit');assert.deepEqual(JSON.parse(JSON.stringify(calls[0].options)),{answers:{q1:1}});
 assert.match(text(card),/Correct/);assert.match(text(card),/Server checked <b>answer<\/b>/);assert.ok(controls.every(c=>c.disabled));
 quiz.handleEvent({task_id:'t',type:'result',data:{items:[],quiz_status:{status:'partial'}}});assert.equal(roles(container,'item').length,1);
 quiz.handleEvent(event(2,q('q2','multiple_choice')));card=roles(container,'item')[1];controls=roles(card,'answer');controls[0].checked=true;controls[2].checked=true;
 await roles(card,'form')[0].handlers.submit({preventDefault(){}});assert.deepEqual(JSON.parse(JSON.stringify(calls[1].options)),{answers:{q2:[0,2]}});
 quiz.handleEvent(event(3,{id:'q3',type:'short_answer',question:'Explain.'}));card=roles(container,'item')[2];roles(card,'answer')[0].value='My explanation';
 await roles(card,'form')[0].handlers.submit({preventDefault(){}});assert.deepEqual(JSON.parse(JSON.stringify(calls[2].options)),{answers:{q3:'My explanation'}});
 quiz.handleEvent(event(4,{id:'q4',type:'fill_blank',question:'Fill {{a}} and {{b}}.',blanks:[{id:'a'},{id:'b'}]}));card=roles(container,'item')[3];controls=roles(card,'answer');controls[0].value='A';controls[1].value='B';
 await roles(card,'form')[0].handlers.submit({preventDefault(){}});assert.deepEqual(JSON.parse(JSON.stringify(calls[3].options)),{answers:{q4:{a:'A',b:'B'}}});
 // A server-returned manual review is displayed without invented correctness.
 quiz.handleEvent({task_id:'t',type:'result',data:{items:[],feedback:[{item_id:'q3',status:'manual_review',score:null,max_score:null,explanation:'Human review required'}]}});
 assert.match(text(roles(container,'item')[2]),/Manual review/);
 quiz.handleEvent({task_id:'old',type:'quiz.question',data:q('q5')});assert.equal(roles(container,'item').length,4);
 // In-flight response after reset must not modify a newer task.
 quiz.handleEvent({task_id:'t',type:'quiz.question',data:q('q5')});card=roles(container,'item')[4];roles(card,'answer')[0].checked=true;
 let resolve;pending=new Promise(r=>{resolve=r;});const submit=roles(card,'form')[0].handlers.submit({preventDefault(){}});
 assert.equal(calls.length,5);const duplicate=roles(card,'form')[0].handlers.submit({preventDefault(){}});await duplicate;assert.equal(calls.length,5);
 quiz.beginTask({taskId:'new'});resolve({feedback:[{item_id:'q5',status:'correct',explanation:'STALE'}]});await submit;assert.ok(!text(container).includes('STALE'));assert.equal(roles(container,'item').length,0);
 quiz.reset();assert.equal(container.hidden,true);assert.equal(container.children.length,0);
 // Error retry and Response-style request helper support.
 let attempts=0;const second=ctx.TutorQuiz.create({container,request:async()=>{attempts++;if(attempts===1)throw Error('secret');return {ok:true,json:async()=>({feedback:[{item_id:'q1',status:'incorrect',explanation:'Server feedback'}]})};}});
 second.beginTask({taskId:'t'});second.handleEvent(event(1,q('q1')));card=roles(container,'item')[0];roles(card,'answer')[0].checked=true;
 await roles(card,'form')[0].handlers.submit({preventDefault(){}});assert.match(text(card),/Try again/);assert.ok(!text(card).includes('secret'));
 await roles(card,'form')[0].handlers.submit({preventDefault(){}});assert.match(text(card),/Incorrect/);
 assert.ok(!fs.readFileSync(__dirname+'/quiz.js','utf8').includes('innerHTML'));
 console.log('quiz delivery UI tests passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
