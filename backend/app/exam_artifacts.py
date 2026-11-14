"""Trusted exam templates. No user/model TeX or URLs are executed.

Version 1 renders canonical strings literally. The optional right-triangle fixture
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
    header=[r'\documentclass[11pt]{article}',r'\usepackage[student]{exam-layout}']+([r'\usepackage{tikz}'] if geometry else [])+[r'\begin{document}']
    answer_header=[r'\documentclass[11pt]{article}',r'\usepackage[answers]{exam-layout}']+([r'\usepackage{tikz}'] if geometry else [])+[r'\begin{document}']
    meta=f"Time: {exam['duration_minutes']} minutes. Total: {exam['total_points']} points."
    paper_tex=header+[r'\ExamTitle{'+tex_text(exam['title'])+'}{Student paper}{'+tex_text(exam['total_points'])+'}{'+tex_text(exam['duration_minutes'])+'}',tex_text(exam['instructions'])]
    answer_tex=answer_header+[r'\ExamTitle{'+tex_text(exam['title'])+'}{Answers}{'+tex_text(exam['total_points'])+'}{'+tex_text(exam['duration_minutes'])+'}']
    paper_md=['# '+md_text(exam['title']),md_text(meta),md_text(exam['instructions'])]
    answer_md=['# '+md_text(exam['title']+' — Answers'),md_text(meta)]
    lookup={(a['section_id'],a['number']):a for a in exam['answer_key']}
    for section in exam['sections']:
        paper_tex += [r'\SectionTitle{'+tex_text(section['title'])+'}',tex_text(section['instructions'])]
        paper_md += ['## '+md_text(section['title']),md_text(section['instructions'])]
        answer_tex += [r'\SectionTitle{'+tex_text(section['title'])+'}']
        answer_md += ['## '+md_text(section['title'])]
        for item in section['items']:
            label=f"{item['number']}. {item['stem']} ({item['points']} points)"
            minimum_lines = 8 if item['choices'] else 4
            paper_tex += [r'\par\Needspace{'+str(minimum_lines)+r'\baselineskip}\noindent '
                          + tex_text(item['number']+'. '+item['stem'])+r' \mbox{\Points{'
                          + tex_text(item['points'])+r'}}\par']
            paper_md += [md_text(label)]
            for choice in item['choices']:
                value=choice['label']+'. '+choice['text']
                paper_tex += [tex_text(value)+r'\par'];paper_md += [md_text(value)]
            has_diagram=geometry and (section['id'],item['number'])==(geometry['section_id'],geometry['number'])
            if has_diagram:
                # Identical trusted source, no model-generated TeX interpolation.
                paper_tex += [r'\begin{center}',tikz_fragment(geometry),r'\end{center}']
                paper_md += ['![Right triangle ABC](assets/diagram.svg)']
            paper_tex += [r'\AnswerSpace{4mm}']
            answer=lookup[(section['id'],item['number'])]
            value=json.dumps(answer['answer'],ensure_ascii=False) if not isinstance(answer['answer'],str) else answer['answer']
            key=f"{section['id']}/{item['number']}: {value}"
            answer_tex += [r'\ExamAnswer{'+tex_text(section['id']+'/'+item['number'])+'}{'+tex_text(value)+' '+tex_text(answer['explanation'])+'}']
            answer_md += [md_text(key),md_text(answer['explanation'])]
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
                  'includes_answer_key':True,'limitations':['Text is escaped literally, not interpreted as mathematical TeX.','Only the explicit right_triangle_area_v1 numeric geometry template is supported.','Bundle contains answers; share student.pdf or exam.md plus assets/diagram.svg separately with students.'],
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
