"""Fail-closed exam contract. No model calls or pedagogical correctness claims.

A text/PDF sample must first be extracted into EXAMPLE_BLUEPRINT's exact schema
and reviewed if extraction is ambiguous. Never infer missing counts or points.
Array order is authoritative; all numbers/labels are strings (e.g. '一', '2(a)').
Each source stem is retained for normalized no-repeat checks, not generation.
JSON is the canonical wire format. output_format describes final rendering.
Validation proves structural fidelity and answer-key reference consistency only;
it cannot prove difficulty, style equivalence, novelty of meaning, factual truth,
or that an answer actually solves the question. Those require separate review.
"""
from copy import deepcopy
from decimal import Decimal
import json
import math
import random
import secrets
import unicodedata


class BlueprintError(ValueError):
    pass


TYPES = {"single_choice", "multiple_choice", "true_false", "short_answer", "fill_blank", "essay"}
SEMANTIC_LIMITS = (
    "Structural checks do not prove answer correctness, difficulty/style equivalence, "
    "or semantic originality. Review model-extracted blueprints and generated answers."
)
EXAMPLE_BLUEPRINT = {
    "version": 1, "title": "Practice exam", "duration_minutes": 30,
    "total_points": 10, "output_format": "markdown",
    "instructions": "Choose one answer for each question.",
    "style_descriptors": ["concise academic language"],
    "sections": [{"id": "A", "title": "Multiple choice", "instructions": "Choose one.",
                  "duration_minutes": 30, "style_descriptors": ["four options"],
                  "slots": [{"number": "1", "type": "single_choice", "points": 10,
                             "choice_labels": ["A", "B", "C", "D"],
                             "style_descriptors": ["one-step arithmetic"],
                             "source_stem": "What is 2 + 3?"}]}],
}


def _check(condition, message):
    if not condition:
        raise BlueprintError(message)


def _keys(obj, expected, path):
    _check(isinstance(obj, dict), f"{path}: expected object")
    _check(set(obj) == set(expected.split()), f"{path}: expected exactly [{expected}]")


def _text(value, path, empty=False):
    _check(isinstance(value, str) and (empty or bool(value.strip())), f"{path}: expected text")


def _number(value, path, allow_zero=False):
    _check(type(value) in (int, float) and math.isfinite(value) and
           (value >= 0 if allow_zero else value > 0), f"{path}: expected finite positive number")


def _styles(value, path):
    _check(isinstance(value, list), f"{path}: expected list")
    for entry in value:
        _text(entry, path)
    _check(len(set(value)) == len(value), f"{path}: duplicate descriptor")


def normalize_stem(stem):
    """Ignore Unicode compatibility forms, case, punctuation and whitespace."""
    _text(stem, "stem")
    return "".join(c for c in unicodedata.normalize("NFKC", stem).casefold() if c.isalnum())


def validate_blueprint(blueprint):
    _keys(blueprint, "version title duration_minutes total_points output_format instructions style_descriptors sections", "blueprint")
    _check(type(blueprint["version"]) is int and blueprint["version"] == 1, "unsupported blueprint version")
    _text(blueprint["title"], "title")
    _text(blueprint["instructions"], "instructions", empty=True)
    _number(blueprint["duration_minutes"], "duration_minutes")
    _number(blueprint["total_points"], "total_points")
    _check(blueprint["output_format"] in ("json", "markdown", "plain_text"), "unsupported output_format")
    _styles(blueprint["style_descriptors"], "style_descriptors")
    sections = blueprint["sections"]
    _check(isinstance(sections, list) and sections, "sections must be a nonempty list")
    ids, numbers, stems, points, times = set(), set(), set(), Decimal(0), []
    for section in sections:
        _keys(section, "id title instructions duration_minutes style_descriptors slots", "section")
        for field in ("id", "title"):
            _text(section[field], f"section.{field}")
        _text(section["instructions"], "section.instructions", empty=True)
        _check(section["id"] not in ids, "duplicate section id")
        ids.add(section["id"])
        if section["duration_minutes"] is not None:
            _number(section["duration_minutes"], "section.duration_minutes")
        times.append(section["duration_minutes"])
        _styles(section["style_descriptors"], "section.style_descriptors")
        _check(isinstance(section["slots"], list) and section["slots"], "section requires slots")
        for slot in section["slots"]:
            _keys(slot, "number type points choice_labels style_descriptors source_stem", "slot")
            _text(slot["number"], "slot.number")
            # Numbering may restart in a new section, but not within a section.
            identity = (section["id"], slot["number"])
            _check(identity not in numbers, "duplicate slot number in section")
            numbers.add(identity)
            _check(isinstance(slot["type"], str) and slot["type"] in TYPES, "unsupported item type")
            _number(slot["points"], "slot.points")
            points += Decimal(str(slot["points"]))
            _styles(slot["style_descriptors"], "slot.style_descriptors")
            labels = slot["choice_labels"]
            _check(isinstance(labels, list), "choice_labels must be a list")
            for label in labels:
                _text(label, "choice label")
            _check(len(set(labels)) == len(labels), "duplicate choice label")
            if slot["type"] in ("single_choice", "multiple_choice"):
                _check(len(labels) >= 2, "choice item needs at least two labels")
            else:
                _check(not labels, "non-choice item must not declare labels")
            stem = normalize_stem(slot["source_stem"])
            _check(stem and stem not in stems, "empty or duplicate normalized source stem")
            stems.add(stem)
    _check(points == Decimal(str(blueprint["total_points"])), "slot points do not sum to total_points")
    _check(all(t is None for t in times) or all(t is not None for t in times), "section times must be all explicit or all null")
    if all(t is not None for t in times):
        _check(sum(Decimal(str(t)) for t in times) == Decimal(str(blueprint["duration_minutes"])), "section times do not sum to duration_minutes")
    return deepcopy(blueprint)


def generation_contract(blueprint, seed=None):
    """Fresh seed by default; seed is sampling guidance, not a novelty guarantee."""
    blueprint = validate_blueprint(blueprint)
    if seed is None:
        seed = secrets.randbits(63)
    _check(type(seed) is int and 0 <= seed < 2**63, "seed must be an integer in [0, 2**63)")
    return {"blueprint": blueprint, "seed": seed, "semantic_limits": SEMANTIC_LIMITS,
            "requirements": ["Preserve exact section/slot order, numbering, types, points, time, instructions and style descriptors.",
                             "Produce novel stems; do not repeat any source or previously generated stem.",
                             "Return canonical JSON matching the example generated schema; answer_key order must match items.",
                             "Choice answers must use declared labels. Boolean answers must be JSON booleans."]}


def validate_generated_exam(blueprint, exam, prior_stems=()):
    """Raise BlueprintError on mismatch; return defensive copy on success.

    exam mirrors blueprint, with seed and answer_key added. Sections contain
    items instead of slots. Items omit source_stem and add stem plus choices
    ([{label, text}]); answers are separate ordered records {section_id, number,
    answer, explanation}. Choice answers are label/string or distinct label/list;
    true_false uses bool; all other types use nonempty strings.
    """
    blueprint = validate_blueprint(blueprint)
    _keys(exam, "version title duration_minutes total_points output_format instructions style_descriptors sections seed answer_key", "exam")
    generation_contract(blueprint, exam["seed"])
    for key in ("version", "title", "duration_minutes", "total_points", "output_format", "instructions", "style_descriptors"):
        _check(type(exam[key]) is type(blueprint[key]) and exam[key] == blueprint[key], f"exam.{key} mismatch")
    _check(isinstance(exam["sections"], list) and len(exam["sections"]) == len(blueprint["sections"]), "section count mismatch")
    forbidden = {normalize_stem(s) for s in prior_stems}
    forbidden.update(normalize_stem(slot["source_stem"]) for sec in blueprint["sections"] for slot in sec["slots"])
    identities = []
    for section, expected in zip(exam["sections"], blueprint["sections"]):
        _keys(section, "id title instructions duration_minutes style_descriptors items", "exam.section")
        for key in ("id", "title", "instructions", "duration_minutes", "style_descriptors"):
            _check(type(section[key]) is type(expected[key]) and section[key] == expected[key], f"section.{key} mismatch")
        _check(isinstance(section["items"], list) and len(section["items"]) == len(expected["slots"]), "item count mismatch")
        for item, slot in zip(section["items"], expected["slots"]):
            _keys(item, "number type points choice_labels style_descriptors stem choices", "item")
            for key in ("number", "type", "points", "choice_labels", "style_descriptors"):
                _check(type(item[key]) is type(slot[key]) and item[key] == slot[key], f"item.{key} mismatch")
            stem = normalize_stem(item["stem"])
            _check(stem and stem not in forbidden, "repeated or empty normalized stem")
            forbidden.add(stem)
            choices = item["choices"]
            _check(isinstance(choices, list) and len(choices) == len(slot["choice_labels"]), "choice count mismatch")
            option_texts = set()
            for choice, label in zip(choices, slot["choice_labels"]):
                _keys(choice, "label text", "choice")
                _check(choice["label"] == label, "choice label/order mismatch")
                normalized = normalize_stem(choice["text"])
                _check(normalized and normalized not in option_texts, "empty or duplicate choice text")
                option_texts.add(normalized)
            identities.append((section["id"], slot))
    answers = exam["answer_key"]
    _check(isinstance(answers, list) and len(answers) == len(identities), "answer key count mismatch")
    for entry, (section_id, slot) in zip(answers, identities):
        _keys(entry, "section_id number answer explanation", "answer_key entry")
        _check(entry["section_id"] == section_id and entry["number"] == slot["number"], "answer key identity/order mismatch")
        _text(entry["explanation"], "answer explanation")
        answer, kind, labels = entry["answer"], slot["type"], slot["choice_labels"]
        if kind == "single_choice":
            _check(isinstance(answer, str) and answer in labels, "single-choice answer must name one label")
        elif kind == "multiple_choice":
            _check(isinstance(answer, list) and answer and all(isinstance(a, str) and a in labels for a in answer), "multiple-choice answer must contain labels")
            _check(len(answer) == len(set(answer)), "duplicate multiple-choice answer label")
        elif kind == "true_false":
            _check(type(answer) is bool, "true_false answer must be boolean")
        else:
            _text(answer, "answer")
    return deepcopy(exam)


def deterministic_sample_exam(blueprint, seed=0):
    """OFFLINE CONTRACT FIXTURE ONLY. Nonsense content, not a student-ready exam.

    Useful for smoke-testing transport/validation without a model. A seed makes
    fixtures reproducible, not pedagogically meaningful or semantically novel.
    """
    contract = generation_contract(blueprint, seed)
    exam = deepcopy(contract["blueprint"])
    exam.update(seed=seed, answer_key=[])
    rng = random.Random(seed)
    for section in exam["sections"]:
        section["items"] = section.pop("slots")
        for item in section["items"]:
            item.pop("source_stem")
            token = rng.getrandbits(96)
            item["stem"] = f"OFFLINE FIXTURE {token}: {section['id']}/{item['number']} (not an exam question)"
            item["choices"] = [{"label": label, "text": f"Fixture option {index}"} for index, label in enumerate(item["choice_labels"])]
            kind, labels = item["type"], item["choice_labels"]
            answer = labels[0] if kind == "single_choice" else [labels[0]] if kind == "multiple_choice" else True if kind == "true_false" else "Fixture answer, not a verified solution"
            exam["answer_key"].append({"section_id": section["id"], "number": item["number"], "answer": answer, "explanation": "Offline fixture only; answer correctness has not been evaluated."})
    return validate_generated_exam(blueprint, exam)


def load_blueprint_json(text):
    """Reject duplicate JSON keys and non-standard NaN/Infinity instead of guessing."""
    def pairs_hook(pairs):
        obj = {}
        for key, value in pairs:
            _check(key not in obj, f"duplicate JSON key: {key}")
            obj[key] = value
        return obj
    def invalid_constant(value):
        raise BlueprintError(f"invalid JSON constant: {value}")
    try:
        return validate_blueprint(json.loads(text, object_pairs_hook=pairs_hook, parse_constant=invalid_constant))
    except (TypeError, json.JSONDecodeError) as exc:
        raise BlueprintError(f"invalid blueprint JSON: {exc}") from exc


def render_exam(exam):
    """Return separately consumable papers and answer keys, with no HTML execution."""
    from copy import deepcopy
    paper = deepcopy(exam)
    answers = paper.pop("answer_key")
    if exam["output_format"] == "json":
        return {"format":"json", "paper":paper, "answer_key":answers}
    md = exam["output_format"] == "markdown"
    paper_lines = [("# " if md else "") + paper["title"],
                   f"时长：{paper['duration_minutes']} 分钟　满分：{paper['total_points']} 分",
                   paper["instructions"]]
    for section in paper["sections"]:
        paper_lines.extend(["", ("## " if md else "") + section["title"], section["instructions"]])
        for item in section["items"]:
            paper_lines.extend(["", f"{item['number']}）{item['stem']}（{item['points']} 分）"])
            paper_lines.extend(f"{choice['label']}. {choice['text']}" for choice in item["choices"])
    answer_lines = [("# " if md else "") + "参考答案"]
    for entry in answers:
        value = entry["answer"]
        if isinstance(value, list):
            value = "、".join(value)
        elif isinstance(value, bool):
            value = "正确" if value else "错误"
        answer_lines.extend(["", f"{entry['section_id']}/{entry['number']}：{value}", entry["explanation"]])
    return {"format":exam["output_format"], "paper":"\n".join(paper_lines), "answer_key":"\n".join(answer_lines)}
