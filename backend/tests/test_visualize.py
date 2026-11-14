"""Offline renderer contract and hostile-input regression tests."""
import copy
import math
import unittest
import xml.etree.ElementTree as ET

from app.visualize import finalize_visual


class FunctionGraphTests(unittest.TestCase):
    def graph(self, content):
        return finalize_visual({"visualization": {"type": "function_graph", "content": content}})

    def spec(self):
        return {"domain": [-2, 2], "samples": 5,
                "curves": [{"function": "quadratic", "parameters": {"a": 2, "b": 1, "c": -3}}]}

    def test_exact_quadratic_points_and_determinism(self):
        spec = self.spec()
        original = copy.deepcopy(spec)
        result = self.graph(spec)
        self.assertEqual(result["computed"]["curves"][0]["points"],
                         [[-2, 3], [-1, -2], [0, -3], [1, 0], [2, 7]])
        self.assertEqual(result, self.graph(spec))
        self.assertEqual(spec, original)
        self.assertTrue(result["rendered"])
        self.assertFalse(result["executable"])
        self.assertEqual(ET.fromstring(result["svg"]).tag, '{http://www.w3.org/2000/svg}svg')

    def test_linear_and_constant(self):
        result = self.graph({"domain": [-2, 2], "samples": 3,
                             "curves": [{"function": "linear", "parameters": {"m": 0, "b": 7}}]})
        self.assertEqual(result["computed"]["curves"][0]["points"], [[-2, 7], [0, 7], [2, 7]])
        lo, hi = result["computed"]["y_range"]
        self.assertLess(lo, 7)
        self.assertGreater(hi, 7)

    def test_trigonometric_parameter_semantics(self):
        result = self.graph({"domain": [0, math.pi], "samples": 3, "curves": [
            {"function": "sine", "parameters": {"amplitude": 2, "offset": 3}},
            {"function": "cosine", "parameters": {"frequency": 2, "phase": math.pi}}]})
        curves = result["computed"]["curves"]
        for actual, expected in zip(curves[0]["points"], [3, 5, 3]):
            self.assertAlmostEqual(actual[1], expected)
        for actual, expected in zip(curves[1]["points"], [-1, 1, -1]):
            self.assertAlmostEqual(actual[1], expected)

    def test_labels_are_inert_xml_text(self):
        label = '<script>alert("x")</script>&'
        result = self.graph({"curves": [{"function": "linear", "label": label}]})
        root = ET.fromstring(result["svg"])
        self.assertNotIn('<script>', result["svg"])
        self.assertIn(label, [node.text for node in root.iter()])
        allowed = {'svg', 'title', 'desc', 'rect', 'line', 'text', 'polyline'}
        for node in root.iter():
            self.assertIn(node.tag.split('}')[-1], allowed)
            self.assertFalse(any(key.startswith('on') for key in node.attrib))

    def test_nonfinite_and_huge_parameters_rejected(self):
        for value in [True, '1', None, float('nan'), float('inf'), -float('inf'), 10**1000, 1e6+1]:
            with self.subTest(value=repr(value)[:30]), self.assertRaises(ValueError):
                self.graph({"curves": [{"function": "quadratic", "parameters": {"a": value}}]})

    def test_domains_rejected(self):
        for domain in [[1, 1], [2, -2], [0, 1e-7], [0], [False, 2], [-10001, 2], [0, float('nan')], '0,2', [0, 10**1000]]:
            with self.subTest(domain=str(domain)[:40]), self.assertRaises(ValueError):
                self.graph({"domain": domain, "curves": [{"function": "linear"}]})

    def test_resource_limits(self):
        for samples in [True, 1, 502, 2.0, '101']:
            with self.subTest(samples=samples), self.assertRaises(ValueError):
                self.graph({"samples": samples, "curves": [{"function": "linear"}]})
        for curves in [[], [{}] * 9, None]:
            with self.assertRaises(ValueError): self.graph({"curves": curves})
        result = self.graph({"samples": 501, "curves": [{"function": "linear"}] * 8})
        self.assertEqual(len(result['computed']['curves']), 8)
        self.assertEqual(len(result['computed']['curves'][0]['points']), 501)

    def test_no_expression_or_generated_code_path(self):
        for curve in [
            {"function": "eval", "parameters": {}},
            {"function": "__import__('os').system('whoami')"},
            {"function": "linear", "expression": "x*x"},
            {"function": "linear", "parameters": {"code": "print(1)"}},
            {"function": []}, {"function": "linear", "label": "bad\x00label"},
            {"function": "linear", "label": "a"*81},
        ]:
            with self.subTest(curve=curve), self.assertRaises(ValueError):
                self.graph({"curves": [curve]})
        with self.assertRaises(ValueError):
            self.graph({"curves": [{"function": "linear"}], "script": "anything"})

    def test_extreme_valid_numbers_stay_finite(self):
        result = self.graph({"domain": [-10000, 10000], "samples": 501,
                             "curves": [{"function": "quadratic", "parameters": {"a": 1e6, "b": 1e6, "c": 1e6}}]})
        self.assertTrue(all(math.isfinite(y) for _, y in result['computed']['curves'][0]['points']))
        self.assertNotIn('nan', result['svg'])
        self.assertNotIn('inf', result['svg'])

    def test_legacy_exports_remain_explicitly_unsupported(self):
        for kind in ['html', 'svg', 'mermaid', 'manim']:
            output = finalize_visual({'visualization': {'type': kind, 'content': '<script>bad()</script>'}})
            self.assertFalse(output['rendered'])
            self.assertFalse(output['executable'])
            self.assertEqual(output['status'], 'unsupported')
            self.assertNotIn('svg', output)
        with self.assertRaises(ValueError):
            finalize_visual({'visualization': {'type': 'javascript', 'content': 'alert(1)'}})

    def test_existing_chart_contract_preserved(self):
        for kind in ['bar', 'line']:
            chart = {'type': kind, 'labels': ['A', 'B'], 'values': [-1, 3]}
            result = finalize_visual({'chart': chart})
            self.assertEqual(result['type'], 'chart')
            self.assertEqual(result['content'], chart)
            self.assertTrue(result['rendered'])
            ET.fromstring(result['svg'])


if __name__ == '__main__':
    unittest.main()
