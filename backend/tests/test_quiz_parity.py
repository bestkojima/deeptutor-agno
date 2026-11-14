"""Structural multi-type quiz checks; no model calls or semantic guarantees."""
import copy
import unittest
from app.core import validate_quiz

class QuizParityTests(unittest.TestCase):
    def choice(self, **updates):
        return dict(question='Which number is even?',options=['1','2','3'],answer_index=1,explanation='2 is divisible by 2.',**updates)
    def valid(self):
        return {'items':[
            self.choice(id='q1'),
            {'id':'q2','type':'multiple_choice','question':'Select even numbers.','options':['2','3','4'],'answer_indices':[0,2],'explanation':'2 and 4 are even.'},
            {'id':'q3','type':'short_answer','question':'Name a prime greater than 2.','answer':'3','accepted_answers':['5','7'],'explanation':'3 has precisely two positive divisors.'},
            {'id':'q4','type':'fill_blank','question':'{{left}} + {{right}} = 4','blanks':[{'id':'left','answer':'2'},{'id':'right','answer':'2','accepted_answers':['two']}],'explanation':'2 + 2 = 4.'}]}
    def reject(self,item):
        with self.assertRaises(ValueError):validate_quiz({'items':[item]})
    def test_legacy_default_and_no_mutation(self):
        result={'items':[self.choice()]};before=copy.deepcopy(result)
        self.assertIs(validate_quiz(result),result);self.assertEqual(before,result)
    def test_all_four_types(self):validate_quiz(self.valid())
    def test_explicit_single_choice(self):validate_quiz({'items':[self.choice(type='single_choice')]})
    def test_multiple_order_not_significant(self):
        item=self.valid()['items'][1];item['answer_indices']=[2,0];validate_quiz({'items':[item]})
    def test_invalid_index_shapes(self):
        for key in [None,True,1.0,-1,3,'1']:
            item=self.choice();item['answer_index']=key;self.reject(item)
    def test_invalid_multiple_keys(self):
        for key in [None,[],[0,0],[True],[3],['1'],0]:
            item=self.valid()['items'][1];item['answer_indices']=key;self.reject(item)
    def test_invalid_options(self):
        for options in [None,'abc',[],['a'],['a',' A '],['a',{}],['a',''],list(map(str,range(21)))]:
            item=self.choice();item['options']=options;self.reject(item)
    def test_text_required_and_bounded(self):
        for field in ('question','explanation'):
            for value in [None,' ',False,{},'x'*10001]:
                item=self.choice();item[field]=value;self.reject(item)
    def test_bad_type_and_conflicting_fields(self):
        self.reject(self.choice(type='essay'))
        self.reject({**self.choice(),'answer':'2'})
        self.reject({**self.valid()['items'][2],'options':['a','b']})
        self.reject({**self.valid()['items'][1],'answer_index':0})
    def test_short_answer_aliases(self):
        for value in [None,[],[''],['x',' X '],['x']*21,[1]]:
            item=self.valid()['items'][2];item['accepted_answers']=value;self.reject(item)
        for value in [None,'',2]:
            item=self.valid()['items'][2];item['answer']=value;self.reject(item)
    def test_blank_markers(self):
        for question in ['{{left}}','{{right}} {{left}}','{{left}} {{left}}','{{left}} {{missing}}','no markers']:
            item=self.valid()['items'][3];item['question']=question;self.reject(item)
    def test_blank_invalid_structure(self):
        for blanks in [[],[{}],[{'id':'bad-id','answer':'2'}],[{'id':'left','answer':'2','code':'no'}],[{'id':'left','answer':''}]]:
            item=self.valid()['items'][3];item['blanks']=blanks;self.reject(item)
    def test_duplicate_ids(self):
        with self.assertRaises(ValueError):validate_quiz({'items':[self.choice(id='a'),self.choice(id=' A ')]})
    def test_limits_and_containers(self):
        for result in [None,[],{}, {'items':[]},{'items':'a'},{'items':[None]},{'items':[self.choice()]*51}]:
            with self.assertRaises(ValueError):validate_quiz(result)
    def test_no_semantic_claim_or_answer_evaluation(self):
        item=self.valid()['items'][2];item['answer']='__import__("os")'
        self.assertEqual(validate_quiz({'items':[item]})['items'][0]['answer'],item['answer'])

if __name__=='__main__':unittest.main()
