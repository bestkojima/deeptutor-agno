import unittest
from app.quiz_workflow import generate_quiz


def item(n=1):
    return {'id':str(n),'question':f'Question {n}?','options':['a','b'],'answer_index':0,'explanation':'Example explanation.'}

class QuizWorkflowTests(unittest.TestCase):
    def setUp(self):self.events=[]
    def emit(self,name,payload):self.events.append((name,payload))
    def run_quiz(self,targets,generate,review=lambda _: {'accepted':True}):
        return generate_quiz(targets,generate,review,self.emit)
    def test_sequential_accepted_context(self):
        seen=[]
        def generate(target,accepted,corrections):
            seen.append([i['id'] for i in accepted]);return item(target['n'])
        result=self.run_quiz([{'n':1},{'n':2}],generate)
        self.assertEqual(seen,[[],['1']]);self.assertEqual(result['quiz_status']['status'],'completed')
        self.assertEqual([name for name,_ in self.events],['quiz.question.started','quiz.question.emitted','quiz.question.started','quiz.question.emitted','quiz.completed'])
    def test_structural_retry_once(self):
        calls=[]
        def generate(target,accepted,corrections):
            calls.append(corrections);return {} if len(calls)==1 else item()
        result=self.run_quiz([{}],generate)
        self.assertEqual(result['quiz_status']['successful'],1);self.assertEqual(len(calls),2);self.assertTrue(calls[1])
    def test_review_rejection_corrections(self):
        notes=[];reviews=[]
        def review(value):
            reviews.append(value);return {'accepted':len(reviews)>1,'corrections':['Check arithmetic']} if len(reviews)==1 else {'accepted':True}
        def generate(t,a,c):notes.append(c);return item()
        result=self.run_quiz([{}],generate,review)
        self.assertEqual(notes,[[],['Check arithmetic']]);self.assertEqual(result['quiz_status']['outcomes'][0]['attempts'],2)
    def test_all_failed_explicit(self):
        result=self.run_quiz([{},{}],lambda *args: {},lambda _:self.fail('invalid item reached review'))
        self.assertEqual(result['items'],[]);self.assertEqual(result['quiz_status']['status'],'failed');self.assertEqual(result['quiz_status']['failed'],2)
    def test_partial_and_no_failed_context(self):
        contexts=[]
        def generate(t,a,c):contexts.append(len(a));return item() if t['ok'] else {}
        result=self.run_quiz([{'ok':False},{'ok':True}],generate)
        self.assertEqual(contexts,[0,0,0]);self.assertEqual(result['quiz_status']['status'],'partial')
    def test_duplicates_retried_then_failed(self):
        result=self.run_quiz([{},{}],lambda *args:item())
        self.assertEqual(result['quiz_status']['successful'],1);self.assertEqual(result['quiz_status']['failed'],1)
    def test_type_constraint(self):
        result=self.run_quiz([{'type':'multiple_choice'}],lambda *args:item())
        self.assertEqual(result['quiz_status']['status'],'failed')
    def test_callback_mutation_isolated(self):
        target={'n':1}
        def generate(t,a,c):t['n']=8; a.clear();return item()
        def review(value):value['question']='mutated';return {'accepted':True}
        result=self.run_quiz([target],generate,review)
        self.assertEqual(target,{'n':1});self.assertEqual(result['items'][0]['question'],'Question 1?')
    def test_bad_verdicts_fail_closed(self):
        for verdict in [None,{}, {'accepted':'yes'}, {'accepted':True,'corrections':'text'}, {'accepted':False,'corrections':[None]}]:
            result=self.run_quiz([{}],lambda *args:item(),lambda _:verdict)
            self.assertEqual(result['quiz_status']['status'],'failed')
    def test_exceptions_redacted(self):
        def generate(*args):raise RuntimeError('secret-token')
        result=self.run_quiz([{}],generate)
        self.assertNotIn('secret-token',str(result)+str(self.events));self.assertEqual(result['quiz_status']['status'],'failed')
    def test_emit_failure_propagates(self):
        def emit(*args):raise OSError('storage full')
        with self.assertRaises(OSError):generate_quiz([{}],lambda *args:item(),lambda _: {'accepted':True},emit)
    def test_invalid_plans(self):
        for targets in [None,[],[{}]*51,[1],[{'type':'unknown'}]]:
            with self.assertRaises(ValueError):self.run_quiz(targets,lambda *args:item())

if __name__=='__main__':unittest.main()
