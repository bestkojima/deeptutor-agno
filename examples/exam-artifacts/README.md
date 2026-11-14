# Issue #7: opt-in exam export

`request.json` is an explicit **synthetic fixture**, not a real generated exam.
POST it to `/api/tasks`. Poll the existing task and read `result.artifacts.files`.
Each entry has a relative allowlisted download URL. `bundle.zip` contains TeX
sources, the shipped `examples/latex-gaokao-i-2026/exam-layout.sty`, student PDF,
answer PDF, `exam.md`, `answers.md`, `canonical.json`, and the exact TikZ-derived
`assets/diagram.svg`. Markdown uses that relative path and works offline when the
ZIP is extracted. The full bundle includes answers: give students `student.pdf`
or only `exam.md` and `assets/diagram.svg`, not the entire bundle.

## Contract and boundary

- Choice duplicate checks preserve mathematical signs, primes, case and
  superscripts: `−1` and `1`, or `AC` and `AC′`, remain distinct. Textually
  duplicate options are still rejected. This check does not prove equivalence
  of different expressions such as `1/2` and `0.5`.
- No `inputs.artifacts`: legacy behavior is unchanged, including fake fixtures.
- `inputs.artifacts: {"version":1}`: export the validated canonical exam as-is;
  no diagram is invented and no model call is added.
- Optional `geometry` supports only `right_triangle_area_v1`, fake provider only,
  with exact `section_id`, `number`, and integer `base`/`height` between 1 and 20.
  This explicitly replaces that single-choice or short-answer slot with a trusted,
  visibly synthetic area question and matching numeric answer. Other slots remain
  unchanged. Blueprint structure, points and ordering are revalidated.
- Geometry labels, both PDF diagrams, and the Markdown SVG come from the same
  numeric record and trusted TikZ fragment. SVG is converted from the diagram-only
  PDF with Poppler; it is not a separately drawn approximation.
- Model/user text, including LaTeX-like formulas, is escaped **literally**. This
  version does not interpret arbitrary math markup or compile supplied TeX.
- Markdown escapes HTML and arbitrary image/link syntax. Only the trusted relative
  SVG image is emitted. No remote resources or model executable code are used.
- The artifact directory is atomically renamed into place only after all outputs
  and the ZIP are complete. Errors remove staging and fail the task; no partial
  manifest or links are published. Download filenames are exact allowlisted paths.
- XeLaTeX runs with `-no-shell-escape`, bounded timeouts, fixed entrypoint names and
  a small allowlisted environment. App/provider secrets are not inherited.

## Dependencies and tests

Install trusted system XeLaTeX, TikZ/PGF, the packages required by the shipped style,
Noto Serif CJK SC (or that style's documented font fallback), and Poppler
`pdftocairo`/`pdftotext`. `dvisvgm` is not required. Set `TUTOR_EXAM_ARTIFACTS` to a
writable server-owned storage directory. Ordinary system TeX installations should
not need custom TEXMF/TEXFORMATS; sandbox installations can configure those on the
server. `XDG_CACHE_HOME` may need a writable directory for font caching.

```sh
cd backend
python -m unittest discover -s tests -p test_exam_artifacts.py -v
RUN_TEX_ARTIFACT_TESTS=1 python -m unittest discover -s tests -p test_exam_artifacts.py -v
```

The normal suite fakes the compiler at the API seam and exercises downloads,
ZIP contents, atomic failure, unchanged defaults, escaping and path rejection.
The opt-in integration test actually compiles both PDFs and the TikZ diagram,
converts SVG, extracts PDF text and checks offline ZIP byte equality. It does not
exercise an external model. TeX failures are reported without including raw logs
or inherited secrets in API errors.

`gaokao-i-2026-structure.json` is the 19-slot structure-only fixture: 8 single
choice, 3 multiple choice, 3 fill blank, 5 written, 150 points, 120 minutes. It
demonstrates preservation of the reviewed shape across seeds. Most stems and
answers are deterministic placeholders, not a usable practice exam.
