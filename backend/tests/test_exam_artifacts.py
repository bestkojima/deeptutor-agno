"""Issue #7 API seam: deterministic opt-in artifacts, never live models."""
import copy
import io
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile
from fastapi.testclient import TestClient
from app import main
from app.exam_blueprint import EXAMPLE_BLUEPRINT

class ExamArtifactApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'TUTOR_EXAM_ARTIFACTS':self.tmp.name+'/artifacts'})
        self.env.start();self.old_db=main.DB;main.DB=Path(self.tmp.name)/'runs.db'
        self.client=TestClient(main.app);self.client.__enter__()
    def tearDown(self):
        self.client.__exit__(None,None,None);main.DB=self.old_db;self.env.stop();self.tmp.cleanup()
    def request(self,artifacts=None):
        inputs={'blueprint':copy.deepcopy(EXAMPLE_BLUEPRINT),'seed':7}
        if artifacts is not None:inputs['artifacts']=artifacts
        response=self.client.post('/api/tasks',json={'capability':'exam','provider':'fake','inputs':inputs})
        self.assertEqual(response.status_code,202,response.text)
        task_id=response.json()['id']
        for _ in range(900):
            task=self.client.get('/api/tasks/'+task_id).json()
            if task['status'] in ('completed','failed'):return task
            time.sleep(.1)
        self.fail('artifact worker timeout')
    def test_opt_in_artifacts_reach_allowlisted_download(self):
        # Fake compiler writes only known outputs; real compiler has its own integration test.
        with patch('app.exam_artifacts._compile_pdf') as compiler, patch('app.exam_artifacts._svg_from_pdf') as svg:
            compiler.side_effect=lambda directory,name:(directory/(name+'.pdf')).write_bytes(b'%PDF-1.4\nfixture')
            svg.side_effect=lambda directory:(directory/'diagram.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
            task=self.request({'version':1,'geometry':{'template':'right_triangle_area_v1','section_id':'A','number':'1','base':3,'height':4}})
        self.assertEqual(task['status'],'completed',task)
        result=task['result'];manifest=result['artifacts']
        self.assertTrue(manifest['synthetic']);self.assertEqual(result['answer_key'][0]['answer'],'A')
        self.assertIn('3',result['sections'][0]['items'][0]['stem'])
        files={f['name']:f for f in manifest['files']}
        for name in ['student.tex','answers.tex','exam-layout.sty','student.pdf','answers.pdf','exam.md','answers.md','diagram.tex','assets/diagram.svg','bundle.zip']:
            self.assertIn(name,files)
            response=self.client.get(files[name]['url']);self.assertEqual(response.status_code,200,name)
        paper=self.client.get(files['exam.md']['url']).text
        self.assertIn('![',paper);self.assertIn('(assets/diagram.svg)',paper)
        self.assertNotIn('Area =',paper)
        answers=self.client.get(files['answers.md']['url']).text;self.assertIn('Area =',answers)
        bundle=self.client.get(files['bundle.zip']['url']).content
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            self.assertIn('assets/diagram.svg',archive.namelist())
            self.assertTrue(all((('/' not in name) or name=='assets/diagram.svg') and not name.startswith('.') for name in archive.namelist()))
        base=files['student.pdf']['url'].rsplit('/',1)[0]
        for name in ['student.log','runs.db','unknown.pdf','%2e%2e%2fstudent.pdf']:
            self.assertEqual(self.client.get(base+'/'+name).status_code,404)
        self.assertNotIn(self.tmp.name,str(manifest))
    def test_default_fake_unchanged(self):
        task=self.request();self.assertEqual(task['status'],'completed',task)
        self.assertNotIn('artifacts',task['result']);self.assertIn('OFFLINE FIXTURE',task['result']['sections'][0]['items'][0]['stem'])
    def test_no_geometry_opt_in_and_shipped_style(self):
        from app.exam_artifacts import STYLE_PATH
        with patch('app.exam_artifacts._compile_pdf') as compiler:
            compiler.side_effect=lambda directory,name:(directory/(name+'.pdf')).write_bytes(b'%PDF-1.4\nfixture')
            task=self.request({'version':1})
        self.assertEqual(task['status'],'completed',task)
        files={f['name']:f for f in task['result']['artifacts']['files']}
        self.assertNotIn('assets/diagram.svg',files)
        self.assertIn('OFFLINE FIXTURE',task['result']['sections'][0]['items'][0]['stem'])
        self.assertEqual(self.client.get(files['exam-layout.sty']['url']).text,STYLE_PATH.read_text())

    def test_compile_failure_has_no_published_manifest(self):
        with patch('app.exam_artifacts._compile_pdf',side_effect=RuntimeError('compiler unavailable')):
            task=self.request({'version':1})
        self.assertEqual(task['status'],'failed');self.assertIsNone(task['result'])
        root=Path(self.tmp.name)/'artifacts'
        self.assertFalse(root.exists() and any(root.iterdir()))


class ExamArtifactSafetyTests(unittest.TestCase):
    def setUp(self):
        from app.exam_blueprint import deterministic_sample_exam
        self.blueprint=copy.deepcopy(EXAMPLE_BLUEPRINT)
        self.exam=deterministic_sample_exam(self.blueprint,7)
    def test_reject_untrusted_spec_and_numeric_values(self):
        from app.exam_artifacts import validate_spec,prepare_canonical
        geometry={'template':'right_triangle_area_v1','section_id':'A','number':'1','base':3,'height':4}
        for spec in [None,{}, {'version':True},{'version':2},{'version':1,'tex':'\\input{secret}'},{'version':1,'geometry':{**geometry,'url':'https://invalid'}}]:
            with self.subTest(spec=spec),self.assertRaises(ValueError):validate_spec(spec)
        for value in [True,0,21,3.5,'3',float('nan')]:
            with self.subTest(value=value),self.assertRaises(ValueError):validate_spec({'version':1,'geometry':{**geometry,'base':value}})
        with self.assertRaises(ValueError):prepare_canonical(self.exam,self.blueprint,{'version':1,'geometry':geometry},'agno')
    def test_renderer_environment_excludes_secrets(self):
        from app.exam_artifacts import _run
        from types import SimpleNamespace
        with patch.dict(os.environ,{'EXAM_TEST_SECRET':'never-forward','OPENAI_API_KEY':'test-not-real'}), patch('app.exam_artifacts.subprocess.run',return_value=SimpleNamespace(returncode=0)) as run:
            _run(['/usr/bin/xelatex','-no-shell-escape','student.tex'],Path('/tmp'))
        environment=run.call_args.kwargs['env']
        self.assertNotIn('EXAM_TEST_SECRET',environment);self.assertNotIn('OPENAI_API_KEY',environment)
        self.assertEqual(environment['shell_escape'],'f');self.assertEqual(environment['openin_any'],'p')

    def test_escape_model_tex_html_and_markdown(self):
        from app.exam_artifacts import render_documents
        poison=r'\input{/etc/passwd} \write18{touch hacked} $x$ ![remote](https://evil.test/x) <img src="https://evil.test/x" onerror="alert(1)">'
        self.exam['sections'][0]['items'][0]['stem']=poison
        docs=render_documents(self.exam,None)
        self.assertNotIn(r'\input{',docs['student.tex']);self.assertNotIn(r'\write18{',docs['student.tex'])
        self.assertIn(r'\textbackslash{}input\{',docs['student.tex'])
        self.assertNotIn('<img',docs['exam.md']);self.assertNotIn('![remote](',docs['exam.md'])
        self.assertIn(r'\!\[remote\]\(',docs['exam.md']);self.assertIn('&lt;img',docs['exam.md'])
    def test_unicode_indices_use_trusted_glyph_fallback(self):
        from app.exam_artifacts import tex_text,render_documents
        self.assertEqual(tex_text('x⁵+aₙ²'), r'x\textsuperscript{5}+a\textsubscript{n}\textsuperscript{2}')
        self.assertEqual(tex_text('x⁻¹'), r'x\textsuperscript{-}\textsuperscript{1}')
        self.assertEqual(tex_text('ₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ'), ''.join(r'\textsubscript{'+c+'}' for c in 'hijklmnoprstuvx'))
        self.assertNotIn(r'\input{',tex_text('⁵'+r'\input{secret}'))
        self.exam['sections'][0]['items'][0]['stem']='求(1+2x)⁵及aₙ的值。'
        docs=render_documents(self.exam,None)
        self.assertIn(r'\textsuperscript{5}',docs['student.tex'])
        self.assertIn(r'\textsubscript{n}',docs['student.tex'])
        self.assertIn('⁵',docs['exam.md']);self.assertIn('ₙ',docs['exam.md'])
    def test_same_tikz_source_and_student_answer_separation(self):
        from app.exam_artifacts import prepare_canonical,render_documents,tikz_fragment
        geometry={'template':'right_triangle_area_v1','section_id':'A','number':'1','base':3,'height':4}
        canonical=prepare_canonical(self.exam,self.blueprint,{'version':1,'geometry':geometry},'fake')
        docs=render_documents(canonical,geometry);fragment=tikz_fragment(geometry)
        self.assertIn(fragment,docs['student.tex']);self.assertIn(fragment,docs['answers.tex'])
        self.assertNotIn('Area =',docs['student.tex']);self.assertNotIn('Area =',docs['exam.md'])
        self.assertIn('Area =',docs['answers.tex']);self.assertIn('Area =',docs['answers.md'])
        self.assertIn('OFFLINE FIXTURE',self.exam['sections'][0]['items'][0]['stem'])
    def test_resolver_rejects_symlinks_and_unpublished(self):
        from app.exam_artifacts import resolve_artifact
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'TUTOR_EXAM_ARTIFACTS':tmp}):
            directory=Path(tmp)/('a'*32);directory.mkdir();(directory/'student.pdf').write_bytes(b'%PDF-')
            with self.assertRaises(FileNotFoundError):resolve_artifact('a'*32,'student.pdf')
            (directory/'manifest.json').write_text('{}')
            (directory/'student.pdf').unlink();(directory/'student.pdf').symlink_to(directory/'manifest.json')
            with self.assertRaises(FileNotFoundError):resolve_artifact('a'*32,'student.pdf')
            for name in ['../manifest.json','/etc/passwd','student.log']:
                with self.assertRaises(FileNotFoundError):resolve_artifact('a'*32,name)
    @unittest.skipUnless(os.getenv('RUN_TEX_ARTIFACT_TESTS')=='1','Opt in to installed XeLaTeX/Poppler integration')
    def test_real_pdf_svg_and_offline_bundle(self):
        from app.exam_artifacts import build_exam_artifacts,resolve_artifact
        import subprocess
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'TUTOR_EXAM_ARTIFACTS':tmp}):
            geometry={'template':'right_triangle_area_v1','section_id':'A','number':'1','base':3,'height':4}
            canonical,manifest=build_exam_artifacts(self.exam,self.blueprint,{'version':1,'geometry':geometry},'fake')
            root=Path(tmp)/manifest['id']
            for name in ['student.pdf','answers.pdf']:
                text=subprocess.run(['pdftotext',str(root/name),'-'],capture_output=True,text=True,check=True).stdout
                self.assertIn('Triangle ABC',text) if name=='student.pdf' else self.assertIn('Area',text)
                if name=='student.pdf':self.assertNotIn('Area =',text)
            self.assertIn('<svg',(root/'assets/diagram.svg').read_text())
            self.assertNotIn('http://evil',(root/'assets/diagram.svg').read_text())
            with zipfile.ZipFile(root/'bundle.zip') as archive:
                for name in ['student.pdf','answers.pdf','exam.md','answers.md','assets/diagram.svg']:
                    self.assertEqual(archive.read(name),(root/name).read_bytes())
            self.assertEqual(resolve_artifact(manifest['id'],'student.pdf'),root/'student.pdf')
            # A separate no-geometry export proves literal TeX/Markdown text is
            # compiled as text, not interpreted as commands or remote content.
            hostile=copy.deepcopy(self.exam)
            hostile['sections'][0]['items'][0]['stem']=r'Literal \input{/etc/passwd} $x$ ![remote](https://example.invalid/image) <img src="x">'
            _,plain_manifest=build_exam_artifacts(hostile,self.blueprint,{'version':1},'fake')
            plain=Path(tmp)/plain_manifest['id']
            text=subprocess.run(['pdftotext',str(plain/'student.pdf'),'-'],capture_output=True,text=True,check=True).stdout
            self.assertIn('input',text);self.assertNotIn('root:x:',text)
            self.assertNotIn('assets/diagram.svg',[entry['name'] for entry in plain_manifest['files']])


if __name__=='__main__':unittest.main()
