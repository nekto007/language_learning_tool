import re
import unicodedata

TOKEN = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")
IRREGULAR = {
    "broke": ["break"],
    "broken": ["break"],
    "spilt": ["spill"],
    "hit": ["hit"],
    "went": ["go"],
    "gone": ["go"],
    "saw": ["see"],
    "seen": ["see"],
    "ran": ["run"],
    "ate": ["eat"],
    "eaten": ["eat"],
    "took": ["take"],
    "taken": ["take"],
    "bought": ["buy"],
    "brought": ["bring"],
    "thought": ["think"],
    "taught": ["teach"],
    "caught": ["catch"],
    "wrote": ["write"],
    "written": ["write"],
    "spoke": ["speak"],
    "spoken": ["speak"],
    "gave": ["give"],
    "given": ["give"],
    "made": ["make"],
    "felt": ["feel"],
    "kept": ["keep"],
    "slept": ["sleep"],
    "stood": ["stand"],
    "understood": ["understand"],
    "wound": ["wind"],
    "lay": ["lie"],
    "lain": ["lie"],
    "left": ["leave"],
    "found": ["find"],
    "bound": ["bind"],
    "leaves": ["leaf", "leave"],
    "children": ["child"],
    "mice": ["mouse"],
    "teeth": ["tooth"],
    "feet": ["foot"],
    "men": ["man"],
    "women": ["woman"],
    "better": ["good", "well"],
}


def key(value):
    return " ".join(unicodedata.normalize("NFKC", value).replace("’", "'").lower().split())


def expression_candidates(sentence, start, end):
    """Read the owner's current idiom/phrasal markings, without a copied catalog."""
    from app.words.models import CollectionWords
    entries=CollectionWords.query.filter(CollectionWords.item_type.in_(['idiom','phrasal_verb'])).order_by(CollectionWords.id).limit(3000).all()
    result = []
    for entry in entries:
        if not (entry.russian_word or '').strip(): continue
        words=key(entry.english_word).split()
        if not words: continue
        first=words[0]
        forms={first,first+'s',first+'ed',first+'ing'}
        forms.update(form for form,bases in IRREGULAR.items() if first in bases)
        if first.endswith('e'): forms.update([first+'d',first[:-1]+'ing'])
        if len(first)>2 and first[-1] not in 'aeiouwxy' and first[-2] in 'aeiou':
            forms.update([first+first[-1]+'ed',first+first[-1]+'ing'])
        parts=['(?:'+'|'.join(re.escape(v) for v in sorted(forms))+')']
        for word in words[1:]:
            if word in ["someone's","one's",'my','your','his','her','our','their']:
                parts.append(r"(?:my|your|his|her|our|their|someone['’]s|one['’]s)")
            else: parts.append(re.escape(word).replace("'","['’]"))
        gap=r'(?:\s+[A-Za-z]+){0,4}' if entry.item_type=='phrasal_verb' and len(words)==2 else ''
        pattern=parts[0]+gap+(r'\s+'+r'\s+'.join(parts[1:]) if len(parts)>1 else '')
        for match in re.finditer(r'(?<![A-Za-z])(?:'+pattern+r')(?![A-Za-z])',sentence,re.I):
            if gap and any(token.lower() in {'not','never','and','or','but','to','do','does','did','is','are','was','were'}
                           for token in match.group().split()[1:-1]):
                continue
            if match.start()<=start and match.end()>=end:
                result.append(dict(id=entry.id,lemma=entry.english_word,sourceText=match.group(),
                    translation=entry.russian_word[:400],kind=entry.item_type,example=(entry.usage_context or entry.sentences or '')[:1000]))
    return sorted(result, key=lambda item: -len(item['sourceText']))[:16]


def dictionary_terms(sentence, start, end, lemma):
    tokens = list(TOKEN.finditer(sentence))
    needles = {key(sentence[start:end]), key(lemma)}
    # Native lemmatization can return inflected forms unchanged. Generate
    # candidates, then let the real dictionary/context decide; never force a stem.
    for form in list(needles):
        if not re.fullmatch("[a-z]+", form):
            continue
        needles.update(IRREGULAR.get(form, []))
        if form.endswith("ies") and len(form) > 4:
            needles.add(form[:-3] + "y")
        if form.endswith("s") and len(form) > 3:
            needles.add(form[:-1])
        if form.endswith("es") and len(form) > 4:
            needles.add(form[:-2])
        for suffix in ("ed", "ing"):
            if form.endswith(suffix) and len(form) > len(suffix) + 2:
                stem = form[: -len(suffix)]
                needles.update((stem, stem + "e"))
                if len(stem) > 2 and stem[-1] == stem[-2]:
                    needles.add(stem[:-1])
                if stem.endswith("i"):
                    needles.add(stem[:-1] + "y")
    for left, token in enumerate(tokens):
        if token.start() > start:
            break
        for right in range(left, min(len(tokens), left + 7)):
            if tokens[right].end() >= end and tokens[right].start() < end + 250:
                needles.add(key(sentence[token.start() : tokens[right].end()]))
    return needles


def dictionary_candidates(sentence, start, end, lemma):
    from sqlalchemy import func
    from app.words.models import CollectionWords

    needles = dictionary_terms(sentence, start, end, lemma)
    entries = (
        CollectionWords.query.filter(
            func.lower(CollectionWords.english_word).in_(needles), CollectionWords.russian_word.isnot(None)
        )
        .order_by(CollectionWords.id)
        .limit(24)
        .all()
    )
    return [
        dict(
            id=word.id,
            english=word.english_word,
            translation=word.russian_word[:1000],
            example=(word.usage_context or word.sentences or "")[:1000],
            kind=word.item_type or "word",
            frequencyBand=word.frequency_band,
            level=word.level,
        )
        for word in entries
        if (word.russian_word or "").strip()
    ]
