// Run with node --test; no browser account, database, or network needed.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
    constructor(tag, text) {
        this.tagName = tag.toUpperCase();
        this.namespaceURI = 'http://www.w3.org/1999/xhtml';
        this.nodeType = tag === '#text' ? 3 : 1;
        this.childNodes = [];
        this.dataset = {};
        this.attributes = {};
        this.style = {};
        this.ownText = text || '';
    }
    set innerHTML(_value) { throw new Error('Untrusted live HTML parsing'); }
    set textContent(value) { this.ownText = String(value); this.childNodes = []; }
    get textContent() { return this.ownText + this.childNodes.map(child => child.textContent).join(''); }
    setAttribute(key, value) { this.attributes[key] = String(value); }
    appendChild(child) {
        if (child.tagName === '#FRAGMENT') this.childNodes.push(...child.childNodes);
        else this.childNodes.push(child);
        return child;
    }
    replaceChildren(...children) { this.childNodes = []; children.forEach(child => this.appendChild(child)); }
}

function descendants(root) {
    return root.childNodes.flatMap(child => [child, ...descendants(child)]);
}

function documentFor(root) {
    return {
        getElementById: () => root,
        createElement: tag => new Element(tag),
        createDocumentFragment: () => new Element('#fragment'),
        createTextNode: text => new Element('#text', text),
        body: new Element('body'),
    };
}

test('admin user rows preserve malicious stored names/emails as text and data only', () => {
    const source = fs.readFileSync('app/templates/admin/modules/list.html', 'utf8');
    const render = source.slice(source.indexOf('function renderModalUsers(users)'), source.indexOf('// Update counts'));
    const table = new Element('tbody');
    const context = vm.createContext({document: documentFor(table)});
    vm.runInContext(render, context);
    const users = [
        {id: 1, username: '<img src=x onerror=alert(1)>', email: '" onmouseover="alert(1)', has_module: false},
        {id: 2, username: '<svg onload=alert(1)>', email: null, has_module: true, is_admin: true, granted_by_admin: true},
    ];
    context.renderModalUsers(users);
    assert.equal(table.childNodes.length, 2);
    for (const [index, row] of table.childNodes.entries()) {
        const user = users[index];
        assert.equal(row.childNodes.length, 6);
        assert.equal(row.dataset.username, user.username.toLowerCase());
        assert.equal(row.dataset.email, (user.email || '').toLowerCase());
        assert.ok(row.childNodes[2].textContent.includes(user.username));
        const button = row.childNodes[5].childNodes[0];
        assert.equal(button.dataset.username, user.username);
        assert.equal(button.dataset.userId, String(user.id));
        assert.equal(button.dataset.action, user.has_module ? 'modal-revoke-module' : 'modal-grant-module');
    }
    assert.equal(descendants(table).some(node => ['IMG', 'SVG', 'SCRIPT'].includes(node.tagName)), false);
});

for (const page of ['list', 'edit']) {
    test(`admin ${page} toast never parses a returned error message`, () => {
        const source = fs.readFileSync(`app/templates/admin/modules/${page}.html`, 'utf8');
        const toast = source.slice(source.indexOf('function showToast('), source.indexOf('// Event delegation'));
        const document = documentFor(new Element('div'));
        const context = vm.createContext({document, setTimeout: () => {}});
        vm.runInContext(toast, context);
        const message = '<img src=x onerror=alert(1)>';
        context.showToast(message, 'danger');
        const rendered = document.body.childNodes[0];
        assert.equal(rendered.textContent, message);
        assert.deepEqual(rendered.childNodes.map(node => node.tagName), ['BUTTON']);
    });
}

test('book preview reconstructs only formatting and text from an inert parsed tree', () => {
    const source = fs.readFileSync('app/static/js/books/content_editor_optimized.js', 'utf8');
    const start = source.indexOf('function renderBookPreview(');
    const render = source.slice(start, source.indexOf('// Update preview', start));
    const preview = new Element('div');
    const document = documentFor(preview);
    const parsed = new Element('#fragment');
    const paragraph = new Element('p');
    paragraph.attributes = {onclick: 'alert(1)', id: 'contentEditor', style: 'position:fixed'};
    const strong = new Element('strong');
    strong.appendChild(new Element('#text', 'Book emphasis'));
    paragraph.appendChild(strong);
    paragraph.appendChild(new Element('#text', '<img src=x onerror=alert(1)>'));
    paragraph.appendChild(new Element('img'));
    const script = new Element('script');
    script.appendChild(new Element('#text', 'alert(1)'));
    paragraph.appendChild(script);
    const foreign = new Element('svg');
    foreign.namespaceURI = 'http://www.w3.org/2000/svg';
    foreign.appendChild(new Element('#text', 'foreign subtree'));
    paragraph.appendChild(foreign);
    const link = new Element('a');
    link.attributes.href = 'javascript:alert(1)';
    link.appendChild(new Element('#text', 'link label'));
    paragraph.appendChild(link);
    parsed.appendChild(paragraph);
    document.createElement = tag => {
        if (tag !== 'template') return new Element(tag);
        return {set innerHTML(_value) { this.content = parsed; }};
    };
    const context = vm.createContext({document});
    vm.runInContext(render, context);
    context.renderBookPreview('malicious parsed HTML fixture', preview);
    assert.equal(preview.textContent, 'Book emphasis<img src=x onerror=alert(1)>link label');
    assert.deepEqual(descendants(preview).filter(node => node.nodeType === 1).map(node => node.tagName), ['P', 'STRONG']);
    assert.ok(descendants(preview).every(node => Object.keys(node.attributes).length === 0));
});
