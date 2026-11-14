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
    """Validate bounded quiz structure, not semantic correctness or grading.

    Types: single_choice (the legacy default), multiple_choice, short_answer,
    fill_blank. Choice answers use zero-based indices. Short answers use answer
    and optional accepted_answers. Fill blanks use {{id}} markers in question
    and an ordered blanks list of {id, answer, accepted_answers?} objects.
    This validator does not mutate input or evaluate answer expressions.
    """
    def text(value, label, limit=10000):
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError(label + ' must be nonempty bounded text')
        return value.strip().casefold()

    def aliases(record):
        text(record.get('answer'), 'Answer')
        if 'accepted_answers' in record:
            values = record['accepted_answers']
            if not isinstance(values, list) or not 1 <= len(values) <= 20:
                raise ValueError('accepted_answers requires 1–20 text alternatives')
            normalized = [text(value, 'Accepted answer') for value in values]
            if len(set(normalized)) != len(normalized):
                raise ValueError('Accepted answers must be distinct')

    if not isinstance(result, dict):
        raise ValueError('Quiz must be an object')
    items = result.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= 50:
        raise ValueError('Quiz requires 1–50 items')
    ids = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('Each quiz item must be an object')
        question = item.get('question')
        text(question, 'Question')
        text(item.get('explanation'), 'Explanation')
        if 'id' in item:
            identity = text(item['id'], 'Item ID', 100)
            if identity in ids:
                raise ValueError('Quiz item IDs must be unique')
            ids.add(identity)
        kind = item.get('type', 'single_choice')
        if kind not in ('single_choice', 'multiple_choice', 'short_answer', 'fill_blank'):
            raise ValueError('Unsupported quiz type')
        allowed_answers = {
            'single_choice': {'answer_index'},
            'multiple_choice': {'answer_indices'},
            'short_answer': {'answer', 'accepted_answers'},
            'fill_blank': {'blanks'},
        }[kind]
        answer_fields = {'answer_index', 'answer_indices', 'answer', 'accepted_answers', 'blanks'}
        if (set(item) & answer_fields) - allowed_answers:
            raise ValueError('Answer fields conflict with quiz type')
        if kind in ('single_choice', 'multiple_choice'):
            options = item.get('options')
            if not isinstance(options, list) or not 2 <= len(options) <= 20:
                raise ValueError('Choice items require 2–20 options')
            normalized = [text(option, 'Option', 4000) for option in options]
            if len(set(normalized)) != len(options):
                raise ValueError('Distinct options required')
            answers = [item.get('answer_index')] if kind == 'single_choice' else item.get('answer_indices')
            if not isinstance(answers, list) or not 1 <= len(answers) <= len(options):
                raise ValueError('A nonempty answer key is required')
            if any(type(index) is not int or not 0 <= index < len(options) for index in answers):
                raise ValueError('Invalid answer key')
            if len(set(answers)) != len(answers):
                raise ValueError('Answer indices must be unique')
        else:
            if 'options' in item:
                raise ValueError('Non-choice items must not contain options')
            if kind == 'short_answer':
                aliases(item)
            else:
                blanks = item.get('blanks')
                if not isinstance(blanks, list) or not 1 <= len(blanks) <= 20:
                    raise ValueError('Fill items require 1–20 blanks')
                blank_ids = []
                for blank in blanks:
                    if not isinstance(blank, dict) or set(blank) - {'id', 'answer', 'accepted_answers'}:
                        raise ValueError('Invalid blank record')
                    identity = blank.get('id')
                    if not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,39}', identity):
                        raise ValueError('Invalid blank ID')
                    blank_ids.append(identity)
                    aliases(blank)
                markers = re.findall(r'\{\{([^{}]*)\}\}', question)
                if len(set(blank_ids)) != len(blank_ids) or markers != blank_ids:
                    raise ValueError('Each blank requires one matching {{id}} marker in list order')
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
