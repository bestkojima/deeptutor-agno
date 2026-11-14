import copy
import json
import unittest

from app.exam_blueprint import (
    EXAMPLE_BLUEPRINT, BlueprintError, deterministic_sample_exam,
    generation_contract, load_blueprint_json, validate_blueprint,
    validate_generated_exam,
)


class ExamContractTests(unittest.TestCase):
    def setUp(self):
        self.bp = copy.deepcopy(EXAMPLE_BLUEPRINT)
        self.exam = deterministic_sample_exam(self.bp, seed=42)

    def reject(self, change):
        change(self.exam)
        with self.assertRaises(BlueprintError):
            validate_generated_exam(self.bp, self.exam)

    def test_valid_roundtrip_and_defensive_copy(self):
        self.assertEqual(load_blueprint_json(json.dumps(self.bp)), self.bp)
        result = validate_generated_exam(self.bp, self.exam)
        result['sections'].clear()
        self.assertEqual(len(self.exam['sections']), 1)

    def test_seed_reproducibility_and_variation(self):
        self.assertEqual(self.exam, deterministic_sample_exam(self.bp, 42))
        self.assertNotEqual(self.exam, deterministic_sample_exam(self.bp, 43))
        self.assertIsInstance(generation_contract(self.bp)['seed'], int)
        for bad in (True, -1, 2**63, '1', 1.0):
            with self.assertRaises(BlueprintError):
                generation_contract(self.bp, bad)

    def test_missing_and_unknown_schema_keys_rejected(self):
        for mutation in (lambda b: b.pop('duration_minutes'), lambda b: b.update(unknown=1)):
            bp = copy.deepcopy(self.bp)
            mutation(bp)
            with self.assertRaises(BlueprintError):
                validate_blueprint(bp)

    def test_points_and_time_totals(self):
        for field in ('total_points', 'duration_minutes'):
            bp = copy.deepcopy(self.bp)
            bp[field] += 1
            with self.assertRaises(BlueprintError):
                validate_blueprint(bp)

    def test_duplicate_json_keys_and_nonfinite_rejected(self):
        for text in ('{"version":1,"version":1}', '{"points":NaN}', '{bad'):
            with self.assertRaises(BlueprintError):
                load_blueprint_json(text)

    def test_metadata_mismatch(self):
        for field, value in [('title', 'Changed'), ('duration_minutes', 31), ('total_points', 11),
                             ('output_format', 'json'), ('instructions', 'Changed'), ('style_descriptors', [])]:
            exam = copy.deepcopy(self.exam)
            exam[field] = value
            with self.assertRaises(BlueprintError):
                validate_generated_exam(self.bp, exam)

    def test_item_structure_mismatch(self):
        for field, value in [('number', '2'), ('type', 'essay'), ('points', 20),
                             ('choice_labels', ['B', 'A', 'C', 'D']), ('style_descriptors', [])]:
            exam = copy.deepcopy(self.exam)
            exam['sections'][0]['items'][0][field] = value
            with self.assertRaises(BlueprintError):
                validate_generated_exam(self.bp, exam)

    def test_missing_item_or_answer(self):
        self.reject(lambda e: e['sections'][0]['items'].clear())
        self.exam = deterministic_sample_exam(self.bp, 42)
        self.reject(lambda e: e['answer_key'].clear())

    def test_answer_reference_and_choice_validation(self):
        for field, value in [('number', '2'), ('section_id', 'B'), ('answer', 'Z'), ('explanation', '')]:
            exam = copy.deepcopy(self.exam)
            exam['answer_key'][0][field] = value
            with self.assertRaises(BlueprintError):
                validate_generated_exam(self.bp, exam)

    def test_source_repeat_normalization(self):
        self.reject(lambda e: e['sections'][0]['items'][0].update(stem='  WHAT IS ２ + ３ !!! '))

    def test_prior_repeat(self):
        stem = self.exam['sections'][0]['items'][0]['stem']
        with self.assertRaises(BlueprintError):
            validate_generated_exam(self.bp, self.exam, prior_stems=[stem])

    def test_choice_text_and_order(self):
        self.reject(lambda e: e['sections'][0]['items'][0]['choices'].reverse())
        self.exam = deterministic_sample_exam(self.bp, 42)
        choices = self.exam['sections'][0]['items'][0]['choices']
        # Choice comparison preserves case because a and A can be distinct
        # mathematical objects. Exact duplicates remain prohibited.
        choices[1]['text'] = '  ' + choices[0]['text'] + '  '
        with self.assertRaises(BlueprintError):
            validate_generated_exam(self.bp, self.exam)

    def test_all_supported_types_and_answer_shapes(self):
        for kind in ('single_choice', 'multiple_choice', 'true_false', 'short_answer', 'fill_blank', 'essay'):
            bp = copy.deepcopy(self.bp)
            slot = bp['sections'][0]['slots'][0]
            slot['type'] = kind
            if kind not in ('single_choice', 'multiple_choice'):
                slot['choice_labels'] = []
            exam = deterministic_sample_exam(bp, 9)
            validate_generated_exam(bp, exam)
            exam['answer_key'][0]['answer'] = 1
            with self.assertRaises(BlueprintError):
                validate_generated_exam(bp, exam)

    def test_math_choices_preserve_negative_and_positive_values(self):
        for values in (("−1", "0", "1", "5"), ("−4", "−3", "−1", "1")):
            with self.subTest(values=values):
                exam = copy.deepcopy(self.exam)
                for choice, value in zip(exam['sections'][0]['items'][0]['choices'], values):
                    choice['text'] = value
                validate_generated_exam(self.bp, exam)

    def test_geometry_choices_preserve_prime_and_operators(self):
        values = ("AC=2√2", "AC′=2√2", "AC⊥BD", "AC∥BD")
        for choice, value in zip(self.exam['sections'][0]['items'][0]['choices'], values):
            choice['text'] = value
        validate_generated_exam(self.bp, self.exam)

    def test_choices_preserve_superscripts_and_variable_case(self):
        values = ("x²", "x2", "a", "A")
        for choice, value in zip(self.exam['sections'][0]['items'][0]['choices'], values):
            choice['text'] = value
        validate_generated_exam(self.bp, self.exam)

    def test_choice_duplicates_normalize_minus_and_whitespace(self):
        for duplicate in ("−1", "  -1  ", "﹣1", "－1"):
            with self.subTest(duplicate=duplicate):
                exam = copy.deepcopy(self.exam)
                choices = exam['sections'][0]['items'][0]['choices']
                choices[0]['text'] = '-1'
                choices[1]['text'] = duplicate
                with self.assertRaises(BlueprintError):
                    validate_generated_exam(self.bp, exam)

    def test_choice_whitespace_only_rejected(self):
        self.reject(lambda e: e['sections'][0]['items'][0]['choices'][0].update(text=' \t\n'))

    def test_duplicate_multiple_choice_answer(self):
        self.bp['sections'][0]['slots'][0]['type'] = 'multiple_choice'
        exam = deterministic_sample_exam(self.bp, 42)
        exam['answer_key'][0]['answer'] = ['A', 'A']
        with self.assertRaises(BlueprintError):
            validate_generated_exam(self.bp, exam)

    def test_restarted_numbering_allowed_section_and_order_strict(self):
        sec = copy.deepcopy(self.bp['sections'][0])
        sec['id'] = 'B'
        sec['slots'][0]['source_stem'] = 'What is 8 times 9?'
        self.bp['sections'].append(sec)
        self.bp['duration_minutes'] = 60
        self.bp['total_points'] = 20
        exam = deterministic_sample_exam(self.bp, 42)
        validate_generated_exam(self.bp, exam)
        exam['answer_key'].reverse()
        with self.assertRaises(BlueprintError):
            validate_generated_exam(self.bp, exam)
        exam = deterministic_sample_exam(self.bp, 42)
        exam['sections'].reverse()
        with self.assertRaises(BlueprintError):
            validate_generated_exam(self.bp, exam)

    def test_duplicate_generated_stems(self):
        slot = copy.deepcopy(self.bp['sections'][0]['slots'][0])
        slot.update(number='2', source_stem='What is 8 times 9?')
        self.bp['sections'][0]['slots'].append(slot)
        self.bp['total_points'] = 20
        exam = deterministic_sample_exam(self.bp, 42)
        items = exam['sections'][0]['items']
        items[1]['stem'] = items[0]['stem']
        with self.assertRaises(BlueprintError):
            validate_generated_exam(self.bp, exam)

    def test_ambiguous_blueprint_rejected(self):
        for change in (
            lambda b: b['sections'][0]['slots'][0].update(type='unknown'),
            lambda b: b['sections'][0]['slots'][0].update(source_stem='?!'),
            lambda b: b['sections'][0]['slots'][0].update(points=True),
            lambda b: b['sections'][0]['slots'][0].update(choice_labels=['A', 'A']),
            lambda b: b['sections'][0]['slots'][0].update(points=float('nan')),
        ):
            bp = copy.deepcopy(self.bp)
            change(bp)
            with self.assertRaises(BlueprintError):
                validate_blueprint(bp)

    def test_fractional_points_exact_decimal(self):
        slots = self.bp['sections'][0]['slots']
        slots[0]['points'] = 0.1
        second = copy.deepcopy(slots[0])
        second.update(number='2', points=0.2, source_stem='Different source question')
        slots.append(second)
        self.bp['total_points'] = 0.3
        validate_blueprint(self.bp)

    def test_no_section_timing_is_valid(self):
        self.bp['sections'][0]['duration_minutes'] = None
        validate_blueprint(self.bp)
        validate_generated_exam(self.bp, deterministic_sample_exam(self.bp, 2))


if __name__ == '__main__':
    unittest.main()
