"""Independent educational kernels; no eval, shell or generated code execution."""
import ast
import operator
import re
from typing import Any

CAPABILITIES = ['chat','ask_questions','quiz','visualize','video_lesson','immersive_reading','research','solve','exam']

def calculate(expression: str) -> float:
    if len(expression) > 200:
        raise ValueError('Expression too long')
    tree = ast.parse(expression, mode='eval')
    operations = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (float,int):
            if abs(node.value) > 1e12: raise ValueError('Number too large')
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub,ast.UAdd)):
            return (-1 if isinstance(node.op,ast.USub) else 1)*visit(node.operand)
        if isinstance(node, ast.BinOp) and type(node.op) in operations:
            value = operations[type(node.op)](visit(node.left), visit(node.right))
            if abs(value) > 1e15: raise ValueError('Result too large')
            return value
        raise ValueError('Only numbers and + - * / parentheses are supported')
    return visit(tree.body)

def validate_sources(sources):
    ids=set()
    for source in sources:
        if not source.get('id') or source['id'] in ids: raise ValueError('Source IDs must be unique')
        ids.add(source['id'])
        if not isinstance(source.get('text'),str): raise ValueError('Source text is required')
        if source.get('page') is not None and (not isinstance(source['page'],int) or source['page']<1): raise ValueError('Invalid page')
        if source.get('start_seconds') is not None:
            if source['start_seconds']<0 or source.get('end_seconds',source['start_seconds'])<source['start_seconds']: raise ValueError('Invalid time range')
    return sources

def verify_grounding(result, sources):
    lookup={s['id']:s for s in sources}
    checked=[]
    for citation in result.get('citations',[]):
        s=lookup.get(citation.get('source_id'))
        quote=citation.get('quote','')
        if not s or not quote or quote not in s['text']: raise ValueError('Citation does not match supplied source text')
        checked.append({**citation, **{k:s[k] for k in ['page','start_seconds','end_seconds'] if k in s}})
    result['citations']=checked
    result['grounding']={'citations_checked':len(checked),'method':'exact source excerpt matching','semantic_entailment_verified':False}
    return result

def validate_quiz(result):
    items=result.get('items',[])
    if not items: raise ValueError('Quiz requires items')
    for item in items:
        options=item.get('options',[])
        if len(options)<2 or len(options)!=len(set(options)): raise ValueError('Distinct options required')
        if type(item.get('answer_index')) is not int or not 0<=item['answer_index']<len(options): raise ValueError('Invalid answer key')
        if not item.get('explanation'): raise ValueError('Explanation required')
    return result

def fake_run(capability, inputs, emit):
    """Explicit, deterministic fixtures. Never impersonates a real model."""
    sources=validate_sources(inputs.get('sources',[]))
    prompt=inputs.get('prompt','')
    emit('step.started',{'name':'deterministic_fixture','demo':True})
    base={'kind':capability,'demo':True,'text':'Offline fixture only. Configure Agno for generated educational content.','citations':[]}
    if capability=='exam':
        from .exam_blueprint import deterministic_sample_exam, validate_generated_exam
        blueprint=inputs.get('blueprint')
        if not blueprint: raise ValueError('Exam requires an explicit reviewed blueprint')
        exam=deterministic_sample_exam(blueprint,inputs.get('seed',0))
        validate_generated_exam(blueprint,exam)
        return exam
    elif capability=='quiz':
        base['items']=[{'id':'q1','question':'What is 2 + 3?','options':['4','5','6'],'answer_index':1,'explanation':'Adding 2 and 3 gives 5.'}]
        validate_quiz(base)
    elif capability=='solve':
        expression=inputs.get('expression',prompt)
        emit('tool.started',{'name':'safe_calculator','input':expression})
        answer=calculate(expression)
        emit('tool.completed',{'name':'safe_calculator','output':answer})
        base.update(text=str(answer),steps=[{'name':'Parse','text':'Parse arithmetic with a restricted AST.'},{'name':'Compute','text':str(answer)},{'name':'Verify','text':'Recomputed with the same safe evaluator; not an independent mathematical proof.'}],verified=calculate(expression)==answer)
    elif capability in ('immersive_reading','research'):
        if not sources: raise ValueError('Provide source excerpts with page or time coordinates; no invented citations')
        citations=[{'source_id':s['id'],'quote':s['text'][:240]} for s in sources if s['text']]
        base.update(text='\n\n'.join(c['quote'] for c in citations),citations=citations)
        if capability=='research': base['agents']=['decompose (fixture)','retrieve supplied excerpts','verify excerpt locations']; base['limitations']=['No live web or arXiv research in fake mode']
    elif capability=='visualize':
        base.update(format='chart',chart={'type':'bar','labels':['A','B','C'],'values':[2,3,5]},available_formats=['chart','html','svg','mermaid'],limitations=['Manim execution disabled until an isolated renderer is configured'])
    elif capability=='video_lesson':
        from .media import build_lesson
        base.update(build_lesson(inputs))
    elif capability=='ask_questions':
        base.update(text='Your answers have been recorded in this run.',answers=inputs.get('answers',{}))
    return verify_grounding(base,sources)
