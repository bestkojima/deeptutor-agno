"""Trusted exam templates. No user/model TeX or URLs are executed.

Canonical strings use bounded, trusted typography; model TeX remains literal. The optional right-triangle fixture
is synthetic and restricted to fake mode; it replaces exactly one nominated slot.
All downloadable outputs are published together only after compilation succeeds.
"""
from copy import deepcopy
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unicodedata
import uuid
import zipfile
from .exam_blueprint import validate_generated_exam

FORMATS = {
    'student.tex':'text/plain', 'answers.tex':'text/plain', 'exam-layout.sty':'text/plain',
    'student.pdf':'application/pdf', 'answers.pdf':'application/pdf',
    'exam.md':'text/markdown', 'answers.md':'text/markdown',
    'diagram.tex':'text/plain', 'assets/diagram.svg':'image/svg+xml', 'diagram.pdf':'application/pdf',
    'canonical.json':'application/json', 'manifest.json':'application/json', 'bundle.zip':'application/zip',
}
STYLE_PATH = Path(__file__).resolve().parents[2]/'examples'/'latex-gaokao-i-2026'/'exam-layout.sty'


def artifact_root():
    return Path(os.environ.get('TUTOR_EXAM_ARTIFACTS', str(Path(__file__).resolve().parents[2]/'exam-artifacts'))).resolve()


def resolve_artifact(artifact_id, filename):
    if not re.fullmatch(r'[a-f0-9]{32}',artifact_id) or filename not in FORMATS:
        raise FileNotFoundError('Unknown exam artifact')
    root=artifact_root();directory=root/artifact_id;path=directory/filename
    if directory.is_symlink() or path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root and parent.is_relative_to(root)) or not path.is_file() or not path.resolve().is_relative_to(directory):
        raise FileNotFoundError('Unknown exam artifact')
    # A UUID directory is made visible only after its complete manifest exists.
    if not (directory/'manifest.json').is_file(): raise FileNotFoundError('Unpublished exam artifact')
    return path


def tex_text(value):
    """Escape TeX input, with trusted glyph fallbacks for Unicode indices.

    These fixed one-character substitutions preserve visible notation when a
    CJK font lacks e.g. superscript 5 or subscript n. They are not a TeX parser.
    """
    escape={'\\':r'\textbackslash{}','{':r'\{','}':r'\}','$':r'\$','&':r'\&',
            '#':r'\#','%':r'\%','_':r'\_','^':r'\textasciicircum{}','~':r'\textasciitilde{}'}
    for source, target in zip('⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ', '0123456789+-=()ni'):
        escape[source] = r'\textsuperscript{' + target + '}'
    for source, target in zip('₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ', '0123456789+-=()aehijklmnoprstuvx'):
        escape[source] = r'\textsubscript{' + target + '}'
    return ''.join(escape.get(c,c) if ord(c)>=32 else ' ' for c in str(value))


def md_text(value):
    # First remove control characters, then escape HTML and Markdown constructs.
    text=''.join(c if ord(c)>=32 else ' ' for c in str(value))
    text=html.escape(text,quote=True)
    return re.sub(r'([\\`*_{}\[\]()#+.!|>~-])',r'\\\1',text)


def md_paragraphs(value):
    return '\n\n'.join(md_text(line) for line in str(value).splitlines())


def tex_paragraphs(value):
    """Preserve explicit paragraphs; accept no TeX supplied by a model.

    Formula recognition is deliberately narrow: Chinese-context runs containing
    only finite math characters. English prose and uncertain runs stay literal.
    Slashes remain slashes, and root scope is parsed rather than guessed.
    """
    return r'\par '.join(_tex_line(line) for line in str(value).splitlines())


def _tex_line(line):
    if re.search(r'_{3,}',line):
        return r'\rule{24mm}{.4pt}'.join(_tex_line(part) for part in re.split(r'_{3,}',line))
    if any(c in line for c in '\\$&%#_^~'):
        return tex_text(line)
    if not re.search(r'[\u4e00-\u9fff]',line):
        return _unicode_math(line) or tex_text(line)
    # Punctuation is retained, and explicit breaks avoid unbreakable coordinate lists.
    parts=re.split(r'([\u4e00-\u9fff，。；：！？、（）①②③]+)',line)
    result=[]
    for part in parts:
        if not part: continue
        math=_unicode_math(part)
        result.append(math if math is not None else tex_text(part))
    return ''.join(result).replace('，',r'，\allowbreak ').replace('；',r'；\allowbreak ')


def _unicode_math(value):
    if not value.strip(): return None
    sub_source='₀₁₂₃₄₅₆₇₈₉ₙ₊₋ᵢₐ';sup_source='⁰¹²³⁴⁵⁶⁷⁸⁹⁻ⁿ'
    symbols={'＝':'=','＋':'+','−':'-','＜':'<','＞':'>','｜':'|','∈':r'\in ','∩':r'\cap ',
             '≤':r'\le ','≥':r'\ge ','≠':r'\ne ','∞':r'\infty ','π':r'\pi ',
             'α':r'\alpha ','θ':r'\theta ','△':r'\triangle ','∠':r'\angle ',
             '⊥':r'\perp ','×':r'\times ','·':r'\cdot ','…':r'\cdots ','′':"'",'∑':r'\sum '}
    allowed=set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 +-*/=<>|()[]{},.\t'+sub_source+sup_source+'√'+''.join(symbols))
    if any(c not in allowed for c in value):return None
    # Do not reinterpret ordinary words as a string of multiplied variables.
    if any(len(word)>3 and word not in ('log','sin','cos','tan','max') for word in re.findall('[A-Za-z]+',value)):
        return None
    text=value.replace('{',r'\{').replace('}',r'\}')
    text=re.sub('['+sub_source+']+',lambda m:'_{'+m[0].translate(str.maketrans(sub_source,'0123456789n+-ia'))+'}',text)
    text=re.sub('['+sup_source+']+',lambda m:'^{'+m[0].translate(str.maketrans(sup_source,'0123456789-n'))+'}',text)
    for source,target in symbols.items():text=text.replace(source,target)
    while '√' in text:
        index=text.index('√');start=index+1
        if start<len(text) and text[start] in '([':
            opener=text[start];closer=')' if opener=='(' else ']';depth=1;end=start+1
            while end<len(text) and depth:
                if text[end]==opener:depth+=1
                elif text[end]==closer:depth-=1
                end+=1
            if depth:return None
            operand=text[start+1:end-1]
        else:
            match=re.match(r'(?:[A-Za-z]+\([^()]*\)|[0-9]+|[A-Za-z])',text[start:])
            if not match:return None
            operand=match[0];end=start+len(operand)
        text=text[:index]+r'\sqrt{'+operand+'}'+text[end:]
    for function in ('log','sin','cos','tan','ln','max'):
        text=re.sub(r'\b'+function+r'\b',lambda m:'\\'+function+' ',text)
    text=text.replace('=',r'=\allowbreak ').replace('<',r'<\allowbreak ').replace('>',r'>\allowbreak ')
    return '$'+text.strip()+'$'


def choice_layout(choices):
    if not choices:return []
    texts=[c['text'] for c in choices]
    # Approximate printable width, not code-point count: Chinese characters
    # and full-width punctuation usually occupy about two Latin glyph cells.
    widths=[sum(2 if unicodedata.east_asian_width(c) in ('W','F') else 1 for c in t) for t in texts]
    prose=any(len(re.findall(r'[\u4e00-\u9fff]',t))>=10 and re.search(r'[，；。]',t) for t in texts)
    if (not prose and len(choices)==4 and [c['label'] for c in choices]==list('ABCD')
            and not any(len(t.splitlines())>1 for t in texts)):
        macro='Choices' if max(widths)<=16 else 'LongChoices' if max(widths)<=42 else None
        if macro:return ['\\'+macro+''.join('{'+tex_paragraphs(c['text'])+'}' for c in choices)]
    # A real list keeps both wrapped lines and extra paragraphs aligned
    # with the option body, not with the A/B/C/D label.
    return [
        r'\begin{list}{}{\setlength{\leftmargin}{2em}\setlength{\labelwidth}{1.5em}'
        r'\setlength{\labelsep}{.5em}\setlength{\itemsep}{2pt}\setlength{\topsep}{2pt}'
        r'\setlength{\parsep}{1pt}}',
        *(r'\item[{\textbf{'+tex_text(c['label'])+r'.}}] '+tex_paragraphs(c['text']) for c in choices),
        r'\end{list}',
    ]


def compact_profile(exam, geometry):
    """Four-page layout only for bounded 19-slot/150-point exam shape.

    Unusually verbose papers and all geometry exports retain natural pagination;
    this is a typography policy, not a modification of the exam blueprint.
    """
    items=[i for s in exam['sections'] for i in s['items']]
    expected=['single_choice']*8+['multiple_choice']*3+['fill_blank']*3+['short_answer']*5
    if geometry or exam['total_points']!=150 or [i['type'] for i in items]!=expected:return False
    if [len(s['items']) for s in exam['sections']]!=[8,3,3,5]:return False
    sizes=[len(i['stem'])+sum(len(c['text']) for c in i['choices']) for i in items]
    return sum(sizes[:8])<=1800 and sum(sizes[8:14])<=1550 and sum(sizes[14:17])<=1000 and sum(sizes[17:])<=1000


def validate_spec(spec):
    if not isinstance(spec,dict) or set(spec)-{'version','geometry'} or type(spec.get('version')) is not int or spec['version']!=1:
        raise ValueError('Exam artifacts require {version:1, geometry?:...}')
    geometry=spec.get('geometry')
    if geometry is not None:
        if not isinstance(geometry,dict) or set(geometry)!={'template','section_id','number','base','height'}:
            raise ValueError('Geometry requires exactly template, section_id, number, base, height')
        if geometry['template']!='right_triangle_area_v1': raise ValueError('Unsupported trusted geometry template')
        for key in ('base','height'):
            if type(geometry[key]) is not int or not 1<=geometry[key]<=20: raise ValueError('Triangle lengths must be integers from 1 to 20')
        if any(not isinstance(geometry[k],str) or not geometry[k] for k in ('section_id','number')):
            raise ValueError('Geometry slot references must be strings')
    return deepcopy(spec)


def prepare_canonical(exam,blueprint,spec,provider):
    exam=validate_generated_exam(blueprint,deepcopy(exam));geometry=spec.get('geometry')
    if geometry:
        if provider!='fake': raise ValueError('Synthetic geometry template is available only in explicit fake mode')
        matches=[item for section in exam['sections'] if section['id']==geometry['section_id'] for item in section['items'] if item['number']==geometry['number']]
        if len(matches)!=1: raise ValueError('Geometry slot does not exist')
        item=matches[0]
        if item['type'] not in ('single_choice','short_answer'): raise ValueError('Geometry fixture requires a single_choice or short_answer slot')
        a,b=geometry['base'],geometry['height'];area=a*b/2
        number=lambda value:format(value,'g')
        item['stem']=f'SYNTHETIC TEMPLATE: Triangle ABC is right-angled at A. AB = {a} cm and AC = {b} cm. Find its area in square centimetres.'
        item['choices']=[{'label':label,'text':number(area+i)} for i,label in enumerate(item['choice_labels'])]
        for answer in exam['answer_key']:
            if (answer['section_id'],answer['number'])==(geometry['section_id'],geometry['number']):
                answer['answer']=item['choice_labels'][0] if item['type']=='single_choice' else number(area)
                answer['explanation']=f'SYNTHETIC TEMPLATE: Area = base × height / 2 = {a} × {b} / 2 = {number(area)} square centimetres.'
        exam=validate_generated_exam(blueprint,exam)
    if len(json.dumps(exam,ensure_ascii=False))>100000 or sum(len(s['items']) for s in exam['sections'])>50:
        raise ValueError('Exam export exceeds bounded rendering limits')
    return exam


def tikz_fragment(geometry):
    # Every token except fixed commands originates in validated integers.
    a,b=geometry['base'],geometry['height'];scale=4/max(a,b)
    return (r'\begin{tikzpicture}[x='+format(scale,'.6f')+'cm,y='+format(scale,'.6f')+'cm]\n'
            +f'\\draw[thick] (0,0) node[below left] {{A}} -- ({a},0) node[below right] {{B}} -- (0,{b}) node[above left] {{C}} -- cycle;\n'
            +r'\draw (0.3,0) -- (0.3,0.3) -- (0,0.3);'+'\n'
            +f'\\node[below] at ({a/2:g},0) {{{a} cm}};\n'
            +f'\\node[left] at (0,{b/2:g}) {{{b} cm}};\n'+r'\end{tikzpicture}'+'\n')


def _run(command,directory):
    env={key:os.environ[key] for key in ('PATH','TEXMF','TEXFORMATS','XDG_CACHE_HOME','LANG','LC_ALL','SYSTEMROOT') if key in os.environ};env.update({'openin_any':'p','openout_any':'p','shell_escape':'f','TEXINPUTS':'.:'})
    try:
        completed=subprocess.run(command,cwd=directory,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60,check=False)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise RuntimeError('Exam renderer unavailable or timed out; configure XeLaTeX and Poppler') from exc
    if completed.returncode: raise RuntimeError('Exam renderer failed; check installed TeX packages/fonts and server renderer configuration')


def _compile_pdf(directory,name):
    if name not in ('student','answers','diagram'):raise ValueError('Unknown trusted TeX entrypoint')
    executable=shutil.which('xelatex')
    if not executable:raise RuntimeError('Exam artifacts require XeLaTeX')
    for _ in range(1 if name=='diagram' else 2):
        _run([executable,'-no-shell-escape','-halt-on-error','-interaction=nonstopmode',name+'.tex'],directory)
    log=directory/(name+'.log')
    if log.is_file():
        contents=log.read_text(errors='replace')
        overflow=re.findall(r'Overfull \\[hv]box \(([0-9.]+)pt too (?:wide|high)\)',contents)
        if any(float(size)>2 for size in overflow) or 'Missing character:' in contents:
            raise RuntimeError('Exam layout overflow or missing glyph; shorten content or use a supported font before publishing')
    pdf=directory/(name+'.pdf')
    if not pdf.is_file() or not pdf.read_bytes().startswith(b'%PDF-'):raise RuntimeError('Compiler did not produce a PDF')


def _svg_from_pdf(directory):
    executable=shutil.which('pdftocairo')
    if not executable:raise RuntimeError('Diagram SVG requires Poppler pdftocairo')
    _run([executable,'-svg','diagram.pdf','diagram.svg'],directory)
    svg=(directory/'diagram.svg').read_text()
    if '<svg' not in svg or re.search(r'(?:href|src)\s*=\s*["\'](?!#)',svg) or '<script' in svg:
        raise RuntimeError('Unexpected external content in generated diagram SVG')


def render_documents(exam,geometry):
    header=[r'\documentclass[11pt]{article}',r'\usepackage[student]{exam-layout}']+([r'\usepackage{tikz}'] if geometry else [])+[r'\setlength{\parskip}{3pt}',r'\renewcommand{\baselinestretch}{1.12}',r'\begin{document}']
    answer_header=[r'\documentclass[11pt]{article}',r'\usepackage[answers]{exam-layout}']+([r'\usepackage{tikz}'] if geometry else [])+[r'\setlength{\parskip}{3pt}',r'\renewcommand{\baselinestretch}{1.12}',r'\begin{document}']
    meta=f"Time: {exam['duration_minutes']} minutes. Total: {exam['total_points']} points."
    paper_tex=header+[r'\ExamTitle{'+tex_text(exam['title'])+'}{学生卷}{'+tex_text(exam['total_points'])+'}{'+tex_text(exam['duration_minutes'])+'}',tex_paragraphs(exam['instructions'])]
    answer_tex=answer_header+[r'\ExamTitle{'+tex_text(exam['title'])+'}{参考答案}{'+tex_text(exam['total_points'])+'}{'+tex_text(exam['duration_minutes'])+'}']
    paper_md=['# '+md_text(exam['title']),md_text(meta),md_text(exam['instructions'])]
    answer_md=['# '+md_text(exam['title']+' — Answers'),md_text(meta)]
    profile = compact_profile(exam, geometry)
    if profile: paper_tex.insert(len(header)+1, r'\CandidateLine')
    ordinal = 0
    lookup={(a['section_id'],a['number']):a for a in exam['answer_key']}
    for section in exam['sections']:
        if profile and ordinal in (8,14): paper_tex += [r'\newpage']
        paper_tex += [r'\SectionTitle{'+tex_text(section['title'])+'}',tex_text(section['instructions'])]
        paper_md += ['## '+md_text(section['title']),md_text(section['instructions'])]
        if not profile: answer_tex += [r'\SectionTitle{'+tex_text(section['title'])+'}']
        answer_md += ['## '+md_text(section['title'])]
        for item in section['items']:
            label=f"{item['number']}. {item['stem']} ({item['points']} points)"
            ordinal += 1
            if profile and ordinal == 18: paper_tex += [r'\newpage']
            paper_tex += [r'\par\Needspace{4\baselineskip}\noindent\textbf{'
                          + tex_text(item['number'])+r'.}\enspace '
                          + tex_paragraphs(item['stem'])+r' \hfill\mbox{\Points{'
                          + tex_text(item['points'])+r'}}\par']
            paper_md += [md_paragraphs(label)]
            paper_tex += choice_layout(item['choices'])
            for choice in item['choices']:
                paper_md += [md_paragraphs(choice['label']+'. '+choice['text'])]
            has_diagram=geometry and (section['id'],item['number'])==(geometry['section_id'],geometry['number'])
            if has_diagram:
                # Identical trusted source, no model-generated TeX interpolation.
                paper_tex += [r'\begin{center}',tikz_fragment(geometry),r'\end{center}']
                paper_md += ['![Right triangle ABC](assets/diagram.svg)']
            paper_tex += [r'\vfill' if profile and (ordinal<=8 or ordinal>=15) else r'\AnswerSpace{3mm}']
            answer=lookup[(section['id'],item['number'])]
            value='、'.join(answer['answer']) if isinstance(answer['answer'],list) and all(isinstance(v,str) for v in answer['answer']) else json.dumps(answer['answer'],ensure_ascii=False) if not isinstance(answer['answer'],str) else answer['answer']
            key=f"{section['id']}/{item['number']}: {value}"
            if profile and ordinal in (6,9,11,15,16,17,18,19): answer_tex += [r'\newpage']
            answer_tex += [r'\Needspace{5\baselineskip}\par\textbf{'
                           +tex_text('第 '+item['number']+' 题' if profile else section['id']+'/'+item['number'])+r'}\par',
                           r'\textbf{答案}\quad '+tex_paragraphs(value)+r'\par',
                           r'\textbf{解析}\par '+tex_paragraphs(answer['explanation'])+r'\par\vspace{2mm}']
            answer_md += [md_paragraphs(key),md_paragraphs(answer['explanation'])]
            if has_diagram:
                answer_tex += [r'\begin{center}',tikz_fragment(geometry),r'\end{center}']
                answer_md += ['![Right triangle ABC](assets/diagram.svg)']
    return {'student.tex':'\n'.join(paper_tex+[r'\end{document}']),
            'answers.tex':'\n'.join(answer_tex+[r'\end{document}']),
            'exam.md':'\n\n'.join(paper_md)+'\n','answers.md':'\n\n'.join(answer_md)+'\n'}


def build_exam_artifacts(exam,blueprint,spec,provider):
    spec=validate_spec(spec);exam=prepare_canonical(exam,blueprint,spec,provider)
    geometry=spec.get('geometry');root=artifact_root();root.mkdir(parents=True,exist_ok=True)
    artifact_id=uuid.uuid4().hex
    staging=Path(tempfile.mkdtemp(prefix='.pending-',dir=root))
    try:
        outputs=render_documents(exam,geometry);outputs['exam-layout.sty']=STYLE_PATH.read_text(encoding='utf-8')
        outputs['canonical.json']=json.dumps(exam,ensure_ascii=False,indent=2)+'\n'
        if geometry:
            outputs['diagram.tex']='\n'.join([r'\documentclass{article}',r'\usepackage[paperwidth=80mm,paperheight=70mm,margin=8mm]{geometry}',r'\usepackage{tikz}',r'\pagestyle{empty}',r'\begin{document}',tikz_fragment(geometry),r'\end{document}'])
        for filename,contents in outputs.items():(staging/filename).write_text(contents,encoding='utf-8')
        if geometry:
            _compile_pdf(staging,'diagram');_svg_from_pdf(staging)
            (staging/'assets').mkdir()
            (staging/'diagram.svg').rename(staging/'assets'/'diagram.svg')
        _compile_pdf(staging,'student');_compile_pdf(staging,'answers')
        names=sorted(outputs.keys()|{'student.pdf','answers.pdf'}|({'assets/diagram.svg','diagram.pdf'} if geometry else set()))
        manifest={'version':1,'id':artifact_id,'synthetic':provider=='fake','geometry_template':geometry['template'] if geometry else None,
                  'includes_answer_key':True,'limitations':['Only allowlisted Unicode math is typeset; unsupported input is escaped literally, never executed as TeX.','Only the explicit right_triangle_area_v1 numeric geometry template is supported.','Bundle contains answers; share student.pdf or exam.md plus assets/diagram.svg separately with students.'],
                  'files':[{'name':name,'url':f'/api/exam-artifacts/{artifact_id}/{name}','media_type':FORMATS[name],'sha256':hashlib.sha256((staging/name).read_bytes()).hexdigest()} for name in names]}
        manifest['files'] += [{'name':'bundle.zip','url':f'/api/exam-artifacts/{artifact_id}/bundle.zip','media_type':FORMATS['bundle.zip']}]
        (staging/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        with zipfile.ZipFile(staging/'bundle.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for name in names+['manifest.json']:archive.write(staging/name,arcname=name)
        # Compiler logs/auxiliaries are not published, even in the output folder.
        for path in staging.iterdir():
            if path.is_file() and path.name not in FORMATS:path.unlink()
        staging.rename(root/artifact_id)
        return exam,manifest
    except BaseException:
        shutil.rmtree(staging,ignore_errors=True)
        raise
