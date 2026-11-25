"""Bounded, local intent recognition for the clothing rehearsal."""

import re

from app.utils.normalization import normalize_quiz_answer

_GREETING = r'(?:(?:hi|hello|excuse me) )?'
_REQUEST = (r'(?:(?:do you have|have you got|is there|can i (?:see|try|have|get)|'
            r'could i (?:see|try|have|get)|could you (?:show me|bring me)|'
            r'id like(?: to try)?|i (?:need|want)) )?')
_SIZE = r'(?:bigger|larger|next)'
_CONTRARY = re.compile(r'\b(?:no|not|never|dont|doesnt|didnt|isnt|arent|wont|cant|cannot|smaller|size down)\b')
_REPEAT = re.compile(r'(?:sorry )?(?:could|can|would) you (?:please )?(?:say (?:that|it) again|repeat(?: that| it)?)(?: please)?')
_COLOR = re.compile(r'(?:what (?:other )?colou?rs? (?:do you have|does it come in|do they come in)|'
                    r'what colou?r (?:is it|are they))')
_NAMED_COLOR = re.compile(
    r'(?:(?:do you have|is there) (?:it in |them in |a )?|(?:does it|do they) come in )'
    r'(blue|red|black|white|green|pink|yellow|orange|purple|brown|grey|gray|beige)(?: one| pair)?(?: please)?',
)
_DECLINE = re.compile(r'(?:no(?: thank you| thanks)?|(?:thanks|thank you) but no|'
                      r'i (?:wont take|dont want) (?:it|them|this|these|the blue one)|ill pass)(?: today)?')
_TRY = re.compile(r'(?:can|could|may) i try (?:it|them) on(?: please)?')
_ACCEPT = re.compile(r'(?:yes|sure|okay|ok|'
                     r'(?:(?:yes|sure|okay|ok) )?(?:ill (?:take|buy)|id like|i(?: will)? (?:take|want)) '
                     r'(?:it|them|this|these|the blue (?:one|jacket|pair|shoes)))(?: please| thanks| thank you)?')


def requests_larger(reply: str, round_name: str, authored: list[str]) -> bool:
    text = normalize_quiz_answer(reply)
    if not text or _CONTRARY.search(text):
        return False
    if any(text == normalize_quiz_answer(answer) for answer in authored):
        return True
    item = r'(?:this|the) jacket' if round_name == 'jacket' else r'(?:these|the) shoes'
    description = r'jacket|one' if round_name == 'jacket' else r'pair|shoes|ones'
    request = (rf'{_GREETING}{_REQUEST}(?:(?:it|them|{item}) in )?(?:a |the )?'
               rf'(?:{_SIZE} (?:size|{description})|(?:one |a )?size (?:up|larger|bigger))'
               rf'(?: (?:for |of )?{item})?(?: please)?')
    size_up = rf'{_GREETING}(?:(?:could|can) i |id like to )?(?:go|try) (?:a |one )?size up(?: please)?'
    return bool(re.fullmatch(request, text) or re.fullmatch(size_up, text))


def offer_intent(reply: str) -> str | None:
    text = normalize_quiz_answer(reply)
    if color := _NAMED_COLOR.fullmatch(text):
        return 'color' if color[1] == 'blue' else 'other_color'
    for intent, pattern in (
        ('repeat', _REPEAT), ('color', _COLOR), ('decline', _DECLINE), ('try', _TRY), ('accept', _ACCEPT),
    ):
        if pattern.fullmatch(text):
            return intent
    return None
