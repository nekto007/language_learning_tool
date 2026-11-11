const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../../app/static/js/lesson-completion.js'), 'utf8');

function page(context) {
  const elements = {};
  function element(id) {
    const node = {
      id, style: {}, attrs: {}, textContent: '',
      firstChild: {nodeType: 3, nodeValue: ''},
      classList: {remove() {}},
      setAttribute(key, value) { this.attrs[key] = value; },
      insertBefore(child) { elements[child.id] = child; },
      focus() {}, scrollIntoView() {},
    };
    if (id) elements[id] = node;
    return node;
  }
  const title = element('title');
  title.textContent = 'Урок завершён!';
  const panel = element('lesson-completion');
  panel.querySelector = () => title;
  element('completion-grade');
  element('completion-score');
  element('lesson-footer');
  const next = element('next');
  const dashboard = element('dashboard');
  element('completion-actions').querySelector = selector => selector.includes('next-slot') ? next : dashboard;
  const window = {
    location: {href: 'https://example.test/curriculum/lesson/42/listening-immersion?from=linear_plan'},
    requestAnimationFrame: callback => callback(),
    linearPlanContext: context,
  };
  vm.runInNewContext(source, {
    window, URL, Node: {TEXT_NODE: 3},
    document: {getElementById: id => elements[id], createElement: () => element(), createTextNode: text => ({nodeValue: text})},
  });
  return {window, elements, title, panel, next, dashboard};
}

for (const [correct, score] of [[0, 0], [3, 100]]) {
  test(`practice result ${correct}/3 has accurate wording and a retry action`, () => {
    const p = page();
    p.window.LessonCompletion.show({title: 'Попытка завершена', grade_name: `Правильно ${correct} из 3`,
      score, allowRetry: true, retry_label: 'Попробовать ещё раз', reviewResults: true});
    assert.equal(p.title.textContent, 'Попытка завершена');
    assert.equal(p.elements['completion-grade'].textContent, `Правильно ${correct} из 3`);
    assert.equal(p.elements['completion-score'].textContent, `${score}%`);
    const retry = p.elements['completion-retry-lesson'];
    assert.equal(retry.textContent, 'Попробовать ещё раз');
    assert.equal(new URL(retry.href).searchParams.get('retry'), 'true');
    assert.equal(new URL(retry.href).searchParams.get('from'), 'linear_plan');
  });
}

test('final plan slot keeps explanations accessible until the learner navigates', () => {
  const p = page({isActive: () => true});
  const original = p.window.location.href;
  p.window.LessonCompletion.show({score: 0, allowRetry: true, reviewResults: true,
    daily_plan_ctx: {is_daily_plan: true, day_secured: true, dashboard_url: '/dashboard'}});
  assert.equal(p.window.location.href, original);
  assert.equal(p.panel.attrs['data-completion-mode'], 'plan');
  assert.equal(p.next.style.display, 'none');
  assert.equal(p.dashboard.attrs.href, '/dashboard?day_secured=1');
  assert.ok(p.elements['completion-retry-lesson']);
});

test('legacy final plan slot still redirects to day completion', () => {
  const p = page({isActive: () => true, clear() {}});
  p.window.LessonCompletion.show({score: 100,
    daily_plan_ctx: {is_daily_plan: true, day_secured: true, dashboard_url: '/dashboard'}});
  assert.equal(p.window.location.href, '/dashboard?day_secured=1');
  assert.equal(p.elements['completion-retry-lesson'], undefined);
});

test('legacy standalone completion retains its title and automatic retry policy', () => {
  const p = page();
  p.window.LessonCompletion.show({score: 100});
  assert.equal(p.title.textContent, 'Урок завершён!');
  assert.equal(p.elements['completion-retry-lesson'], undefined);
});

test('legacy plan lookup also preserves question results instead of redirecting', async () => {
  const p = page({isActive: () => true, fetchNextSlot: async () => ({day_secured: true})});
  const original = p.window.location.href;
  p.window.LessonCompletion.show({score: 0, allowRetry: true, reviewResults: true});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(p.window.location.href, original);
  assert.equal(p.panel.attrs['data-completion-mode'], 'plan');
  assert.equal(p.dashboard.attrs.href, '/dashboard?day_secured=1');
});
