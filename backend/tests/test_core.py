import unittest
from app.core import calculate,verify_grounding,validate_quiz,fake_run
class CoreTests(unittest.TestCase):
 def test_math(self): self.assertEqual(calculate('(2+3)*4'),20)
 def test_reject_code(self):
  for expression in ['__import__("os")','2**9999','[1][0]']:
   with self.assertRaises(ValueError): calculate(expression)
 def test_grounding(self):
  with self.assertRaises(ValueError): verify_grounding({'citations':[{'source_id':'x','quote':'made up'}]},[{'id':'x','text':'real'}])
 def test_quiz(self):
  with self.assertRaises(ValueError): validate_quiz({'items':[{'options':['a','b'],'answer_index':4}]})
 def test_fixture(self): self.assertEqual(fake_run('solve',{'prompt':'4 / 2'},lambda *_:None)['text'],'2.0')
if __name__=='__main__': unittest.main()
