#!/usr/bin/env python3
"""Pre-import corpus validation for module_completed/fixed/*.json.

ERRORS block import (structural / gradeability / leftover generator garbage);
WARNINGS are advisory. Exit code 1 if any ERROR.
"""
import json
import glob
import os
import re
import sys
from collections import Counter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(PROJECT_ROOT, "module_completed", "fixed")

# `python scripts/validate_corpus.py` puts scripts/ on sys.path[0], not the project
# root, so `import app` fails and the runtime schema check used to be skipped while
# the gate still printed PASS. Put the root on the path so the documented invocation
# validates exactly what the admin re-import validates.
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

errors, warnings = [], []
def E(f, m): errors.append(f"{f}: {m}")
def W(f, m): warnings.append(f"{f}: {m}")

GARBAGE = [
    (re.compile(r"\bmodule topic\b", re.I), "leftover 'module topic' placeholder"),
    (re.compile(r"\b(reading|listening) note (one|two|three|four|five|six|seven|eight|nine|ten) (connects|repeats)\b", re.I), "leftover note-boilerplate"),
    (re.compile(r"\b(extension|practice) term (one|two|three|four|five|six|seven|eight|nine|ten)\b", re.I), "leftover fake-vocab 'extension/practice term'"),
    (re.compile(r"Дополнительн\w+ строк\w+ для закреплени", re.I), "leftover placeholder translation"),
    (re.compile(r"what does the (final|extended|last|extra) part help the reader", re.I), "leftover meta comprehension question"),
]
SOUND = re.compile(r"\[sound:[^\]]+\]|/static/[^\"]+\.(?:mp3|wav|ogg)", re.I)


def norm(s): return re.sub(r"\s+", " ", str(s).strip().lower()).strip(" .?!\"'")
def toks(s): return [w for w in re.split(r"\s+", str(s).strip()) if w]
def ptoks(s): return sorted(w.strip(".,!?;:\"'").lower() for w in toks(s) if w.strip(".,!?;:\"'"))


def check_mc(fn, tag, ex):
    if not isinstance(ex, dict):
        return
    opts, cor = ex.get("options"), ex.get("correct")
    if opts and cor is not None:
        if isinstance(cor, int):
            if cor >= len(opts):
                E(fn, f"{tag} correct index {cor} out of range ({len(opts)} options)")
        elif isinstance(cor, str) and cor.strip():
            if cor not in opts and not (cor.isdigit() and int(cor) < len(opts)):
                W(fn, f"{tag} correct '{cor[:30]}' not literally in options (grading coerces)")


def main():
    files = sorted(glob.glob(os.path.join(SRC, "*.json")))
    type_counts = Counter()
    audio_refs = 0
    # module_completed/ is gitignored, so "no files" is the default state of any
    # fresh checkout — and an empty loop leaves `errors` empty, which used to
    # print PASS. A gate that reports success on zero input is the failure mode
    # this script exists to prevent (CNT-011).
    if not files:
        E("<runner>", f"no corpus files found under {SRC} — nothing was validated")
    # Run the app's real import-time schema validator so this gate rejects exactly
    # what the admin re-import would reject (e.g. min-length on item fields).
    try:
        from app.curriculum.validators import LessonContentValidator
    except Exception as _e:
        LessonContentValidator = None
        # Not a note any more: without the runtime schema this gate no longer
        # "rejects exactly what the admin re-import would reject", so it must not
        # report PASS. See CNT-011 in docs/audit/2026-08-08-cross-zone-audit.md.
        E("<runner>", f"app LessonContentValidator unavailable — schema check impossible: {_e}")

    for fp in files:
        fn = os.path.basename(fp)
        raw = open(fp, encoding="utf-8").read()
        try:
            data = json.loads(raw)
        except Exception as e:
            E(fn, f"INVALID JSON: {e}")
            continue
        m = data.get("module")
        if not isinstance(m, dict) or not isinstance(m.get("lessons"), list):
            E(fn, "missing module/lessons structure")
            continue

        for rx, msg in GARBAGE:
            if rx.search(raw):
                E(fn, msg)
        audio_refs += len(SOUND.findall(raw))

        orig = next((fp + e for e in (".bak", ".func.bak", ".derecycle.bak", ".dumptail.bak", ".tail2.bak", ".tail3.bak") if os.path.exists(fp + e)), None)
        if orig:
            try:
                on = len(json.load(open(orig, encoding="utf-8"))["module"]["lessons"])
                if on != len(m["lessons"]):
                    E(fn, f"lesson count changed {on}->{len(m['lessons'])}")
            except Exception:
                pass

        for idx, l in enumerate(m["lessons"]):
            lt = l.get("type")
            type_counts[lt] += 1
            c = l.get("content")
            tag = f"L{idx}[{lt}]"
            if not isinstance(c, dict):
                E(fn, f"{tag} content not an object")
                continue

            if LessonContentValidator is not None:
                try:
                    ok, verr, _ = LessonContentValidator.validate(lt, c)
                except Exception as ex:
                    ok, verr = False, str(ex)
                if not ok:
                    E(fn, f"{tag} import-schema invalid: {str(verr)[:120]}")

            if lt == "vocabulary":
                voc = c.get("vocabulary", [])
                if not voc:
                    E(fn, f"{tag} empty vocabulary")
                for j, e in enumerate(voc or []):
                    if not (e.get("english") and e.get("russian")):
                        E(fn, f"{tag} vocab[{j}] missing english/russian")

            elif lt == "sentence_completion":
                items = c.get("items", [])
                if not items:
                    E(fn, f"{tag} empty items")
                for j, it in enumerate(items or []):
                    if not str(it.get("answer", "")).strip():
                        E(fn, f"{tag} item[{j}] empty answer")

            elif lt == "ordering_quiz":
                ex = c.get("exercises", [])
                if not ex:
                    E(fn, f"{tag} empty exercises")
                for j, it in enumerate(ex or []):
                    w, cor = it.get("words"), it.get("correct")
                    if not w or not cor:
                        E(fn, f"{tag} ex[{j}] missing words/correct")
                    elif ptoks(" ".join(w)) != ptoks(cor):
                        E(fn, f"{tag} ex[{j}] words not a permutation of correct")

            elif lt in ("translation", "translation_quiz"):
                arr = c.get("items") or c.get("exercises") or []
                if not arr:
                    E(fn, f"{tag} empty items/exercises")
                for j, it in enumerate(arr):
                    ru = it.get("russian") or it.get("question")
                    en = it.get("english") or it.get("correct")
                    if not (str(ru).strip() and str(en).strip()):
                        E(fn, f"{tag} item[{j}] missing ru/en")

            elif lt == "final_test":
                if not c.get("passing_score") or not c.get("total_points"):
                    E(fn, f"{tag} missing passing_score/total_points")
                secs = c.get("test_sections", []) or []
                ntotal = sum(len(s.get("exercises", []) or []) for s in secs if isinstance(s, dict))
                if ntotal == 0 and not c.get("exercises"):
                    E(fn, f"{tag} no exercises in final_test")
                for si, s in enumerate(secs):
                    for j, ex in enumerate((s.get("exercises", []) or []) if isinstance(s, dict) else []):
                        check_mc(fn, f"{tag} sec{si}.ex{j}", ex)

            elif lt in ("listening_quiz", "dialogue_completion_quiz", "quiz"):
                ex = c.get("exercises", [])
                if not ex:
                    E(fn, f"{tag} empty exercises")
                for j, e in enumerate(ex or []):
                    check_mc(fn, f"{tag} ex{j}", e)

            elif lt in ("listening_immersion", "shadow_reading"):
                if not str(c.get("text", "")).strip():
                    E(fn, f"{tag} empty text")

        # cross-lesson overlap (advisory)
        tq = {norm(ex.get("question") or ex.get("correct") or "")
              for l in m["lessons"] if l.get("type") == "translation_quiz"
              for ex in (l.get("content", {}) or {}).get("exercises", []) if isinstance(ex, dict)}
        ft = set()
        for l in m["lessons"]:
            if l.get("type") == "final_test":
                for s in (l.get("content", {}) or {}).get("test_sections", []) or []:
                    for ex in s.get("exercises", []) or []:
                        if not isinstance(ex, dict):
                            E(fn, f"L{m['lessons'].index(l)}[final_test] None/non-dict exercise")
                            continue
                        v = ex.get("question") or ex.get("correct") or ""
                        if isinstance(v, str) and len(v.split()) >= 4:
                            ft.add(norm(v))
        ov = {x for x in (tq & ft) if x}
        if ov:
            W(fn, f"{len(ov)} translation_quiz<->final_test overlapping sentences")

    # ---- report ----
    print("=" * 72)
    print(f"CORPUS VALIDATION — {len(files)} modules")
    print("=" * 72)
    print(f"lessons: {sum(type_counts.values())} | types: {len(type_counts)} | audio refs: {audio_refs}")
    print(f"\nERRORS (blocking): {len(errors)}")
    for e in errors[:80]:
        print("  ✗", e)
    if len(errors) > 80:
        print(f"  ... +{len(errors)-80} more")
    print(f"\nWARNINGS (advisory): {len(warnings)}")
    for w in warnings[:40]:
        print("  ⚠", w)
    if len(warnings) > 40:
        print(f"  ... +{len(warnings)-40} more")
    print("\n" + ("✅ PASS — corpus is structurally clean, ready to import"
                  if not errors else f"❌ FAIL — {len(errors)} blocking errors"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
