// Compare with the normalized completions projected by the server for legacy feedback.
function matchesCompletedBlank(answer, question) {
  if (question.type !== 'fill_blank' || question.options?.length || !question.completed_blanks?.length) return false;
  const normalized = answer.normalize('NFKC').replace(/[’‘ʼ＇′]/gu, "'").toLowerCase()
    .replace(/\p{P}/gu, character => character === "'" ? character : ' ')
    .replace(/\s+/gu, ' ').trim();
  return question.completed_blanks.includes(normalized);
}
