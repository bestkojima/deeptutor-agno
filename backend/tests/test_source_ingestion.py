import unittest
from unittest.mock import patch
from app.source_ingestion import ingest_source, IngestionError
from app.core import validate_sources, verify_grounding


class SourceIngestionTests(unittest.TestCase):
    def parse(self, text, name='lesson.vtt'):
        return ingest_source(text.encode('utf-8'), filename=name)

    def test_vtt_bom_metadata_settings_and_overlap(self):
        rows = self.parse('\ufeffWEBVTT\r\n\r\nNOTE metadata\r\nignore\r\n\r\nfirst\r\n00:01.000 --> 00:03.000 align:start\r\n你好\r\n第二行\r\n\r\n00:02.000 --> 00:04.000\r\n重叠有效')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['text'], '你好\n第二行')
        self.assertEqual(rows[0]['start_seconds'], 1)
        self.assertEqual(rows[1]['end_seconds'], 4)
        validate_sources(rows)
        grounded = verify_grounding({'citations': [{'source_id': rows[0]['id'], 'quote': '你好'}]}, rows)
        self.assertEqual(grounded['citations'][0]['start_seconds'], 1)

    def test_srt_hours(self):
        row = self.parse('1\n01:02:03,456 --> 01:02:05,000\nExact caption', 'a.srt')[0]
        self.assertEqual(row['start_seconds'], 3723.456)

    def test_ids_stable_content_scoped_and_markup_inert(self):
        text = 'WEBVTT\n\n00:00.000 --> 00:01.000\n<b>literal</b>'
        a, b = self.parse(text), self.parse(text)
        self.assertEqual(a, b)
        self.assertNotEqual(a[0]['id'], self.parse(text.replace('literal', 'other'))[0]['id'])
        self.assertEqual(a[0]['text'], '<b>literal</b>')

    def test_malformed_inputs_fail_closed(self):
        cases = ['WEBVTT', '00:00.000 --> 00:01.000\ntext',
                 'WEBVTT\n00:00.000 --> 00:01.000\ntext',
                 'WEBVTT\n\n00:61.000 --> 01:02.000\ntext',
                 'WEBVTT\n\n00:01.000 --> 00:01.000\ntext',
                 'WEBVTT\n\n00:02.000 --> 00:03.000\ntext\n\n00:01.000 --> 00:02.000\ntext',
                 'WEBVTT\n\n00:00.000 --> 00:01.000',
                 'WEBVTT\n\n00:00.000 --> 00:01.000\nx\n00:01.000 --> 00:02.000\ny',
                 'WEBVTT\n\n999:00:00.000 --> 999:00:01.000\ntext']
        for value in cases:
            with self.subTest(value=value), self.assertRaises(IngestionError):
                self.parse(value)
        with self.assertRaises(IngestionError):
            self.parse('00:00:00,000 --> 00:00:01,000\ntext', 'x.srt')

    def test_bounds_and_disallowed_inputs(self):
        for name in ['../a.vtt', 'https://example/a.vtt', 'a\\b.srt', 'x.mp4', 'x.pdf']:
            with self.subTest(name=name), self.assertRaises(IngestionError):
                ingest_source(b'x', filename=name)
        for data in [b'', b'\xff', b'WEBVTT\x00', b'x' * 2_000_001]:
            with self.assertRaises(IngestionError):
                ingest_source(data, filename='a.vtt')
        text = 'WEBVTT\n\n00:00.000 --> 00:01.000\ntext'
        with patch('app.source_ingestion.MAX_CUE_CHARS', 2), self.assertRaises(IngestionError):
            self.parse(text)
        with patch('app.source_ingestion.MAX_CUES', 0), self.assertRaises(IngestionError):
            self.parse(text)


if __name__ == '__main__':
    unittest.main()
