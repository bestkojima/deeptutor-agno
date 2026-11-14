import json
import sqlite3
import unittest

class QuizDeliveryTests(unittest.TestCase):
    def setUp(self):
        from app import quiz_delivery as q
        self.q=q;self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;q.init_quiz_db(self.db)
    def tearDown(self):self.db.close()
    def item(self,kind='single_choice'):
        value={'question':'Which choices fit?','type':kind,'explanation':'PRIVATE-EXPLANATION','id':'model-id'}
        if kind=='single_choice':value.update(options=['one','two','three'],answer_index=1)
        elif kind=='multiple_choice':value.update(options=['one','two','three'],answer_indices=[0,2])
        elif kind=='short_answer':value.update(answer='PRIVATE-KEY',accepted_answers=['PRIVATE-ALIAS'])
        else:value.update(question='Complete {{a}}.',blanks=[{'id':'a','answer':'PRIVATE-KEY'}])
        return value
    def accept(self,item=None,position=1):
        return self.q.capture_quiz_event(self.db,'t','quiz.question.emitted',{'position':position,'item':item or self.item(),'review':{'corrections':['PRIVATE-KEY']}})
    def test_item_issued_without_key_or_explanation(self):
        data=self.accept();text=json.dumps(data)
        self.assertEqual(data['item']['id'],'q1');self.assertNotIn('answer_index',text);self.assertNotIn('PRIVATE',text)
        self.assertEqual(data['item']['options'],['one','two','three'])
    def test_failed_later_items_preserve_accepted(self):
        self.accept();self.q.capture_quiz_event(self.db,'t','quiz.question.failed',{'position':2,'corrections':['PRIVATE-KEY']})
        task={'id':'t','status':'failed','result':None,'error':'PRIVATE-KEY'}
        view=self.q.quiz_task_view(self.db,task)
        self.assertEqual(len(view['result']['items']),1);self.assertNotIn('PRIVATE',json.dumps(view))
    def test_whitelist_all_raw_event_paths(self):
        self.accept()
        for kind in ['tool.completed','tool.failed','error','progress','quiz.question.rejected','quiz.completed','result','unknown']:
            data=self.q.public_quiz_event(self.db,'t',kind,{'text':'PRIVATE-KEY','explanation':'PRIVATE-EXPLANATION','corrections':['PRIVATE-KEY'],'result':self.item()})
            self.assertNotIn('PRIVATE',json.dumps(data),kind)
    def test_single_scoring_and_idempotence(self):
        self.accept();result=self.q.submit_quiz(self.db,'t',{'q1':1})
        self.assertEqual(result['feedback'][0]['status'],'correct');self.assertEqual(result['summary']['earned'],1)
        self.assertIn('PRIVATE-EXPLANATION',json.dumps(result))
        self.assertEqual(result,self.q.submit_quiz(self.db,'t',{'q1':1}))
        with self.assertRaises(self.q.QuizSubmissionError) as cm:self.q.submit_quiz(self.db,'t',{'q1':0})
        self.assertEqual(cm.exception.status_code,409)
    def test_multi_exact_set_and_incorrect(self):
        self.accept(self.item('multiple_choice'))
        result=self.q.submit_quiz(self.db,'t',{'q1':[2,0]});self.assertEqual(result['summary']['earned'],1)
        self.accept(self.item(),2)
        result=self.q.submit_quiz(self.db,'t',{'q2':0});self.assertEqual(result['feedback'][1]['status'],'incorrect')
    def test_text_not_auto_scored(self):
        self.accept(self.item('short_answer'));self.accept(self.item('fill_blank'),2)
        result=self.q.submit_quiz(self.db,'t',{'q1':'PRIVATE-KEY','q2':{'a':'PRIVATE-KEY'}})
        self.assertEqual(result['summary']['possible'],0);self.assertEqual(result['summary']['manual_review'],2)
        self.assertTrue(all(f['score'] is None for f in result['feedback']))
    def test_validation_atomic(self):
        self.accept();self.accept(self.item('multiple_choice'),2)
        for answer in [True,'1',-1,3,[],None]:
            with self.assertRaises(self.q.QuizSubmissionError):self.q.submit_quiz(self.db,'t',{'q1':answer})
        with self.assertRaises(self.q.QuizSubmissionError):self.q.submit_quiz(self.db,'t',{'q1':1,'q2':[0,0]})
        self.assertEqual(self.q.quiz_task_view(self.db,{'id':'t','status':'running','result':None,'error':None})['result']['feedback'],[])
    def test_replayed_item_and_final_result_not_duplicate(self):
        self.accept();self.accept()
        self.q.capture_quiz_event(self.db,'t','result',{'items':[self.item()]})
        view=self.q.quiz_task_view(self.db,{'id':'t','status':'completed','result':None,'error':None})
        self.assertEqual(len(view['result']['items']),1)
    def test_unknown_id_and_empty_answers(self):
        self.accept()
        for answers in [{},{'unknown':1},[],None]:
            with self.assertRaises(self.q.QuizSubmissionError):self.q.submit_quiz(self.db,'t',answers)
    def test_persistent_bank_feedback_and_batch_atomicity(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'quiz.db'
            with sqlite3.connect(path) as db:
                db.row_factory=sqlite3.Row;self.q.init_quiz_db(db)
                self.q.capture_quiz_event(db,'persist','quiz.question',self.item())
                self.q.submit_quiz(db,'persist',{'q1':1})
            with sqlite3.connect(path) as db:
                db.row_factory=sqlite3.Row
                result=self.q.quiz_task_view(db,{'id':'persist','status':'failed','result':None,'error':'PRIVATE'})
                self.assertEqual(result['result']['summary']['earned'],1)
                self.assertEqual(result['result']['items'][0]['id'],'q1')
                self.assertNotIn('PRIVATE',result['error'])

    def test_postsubmit_events_remain_redacted(self):
        self.accept();self.q.submit_quiz(self.db,'t',{'q1':1})
        value=self.q.public_quiz_event(self.db,'t','quiz.question.emitted',{'position':1,'item':self.item()})
        self.assertNotIn('PRIVATE',json.dumps(value))

if __name__=='__main__':unittest.main()
