# Jinja2 3.1 templates and HTML

## What it is

**HTML** is the markup language of web pages: text with tags such as `<h1>Title</h1>` and `<form>`. A browser reads it and draws the page. A **template** is an HTML file with holes in it. **Jinja2** is the Python library that fills the holes with values at request time. The pinned version is `jinja2==3.1.6`; Flask uses it for `render_template`. Jinja2 depends on `markupsafe` (`3.0.4`), a small library that marks text as "already safe HTML".

## Why this repository uses it

Cross-site scripting (**XSS**) happens when a page prints text that a user typed and the browser mistakes it for code. The fix is **output encoding**: before printing, turn `<` into `&lt;`, `>` into `&gt;`, `&` into `&amp;`, `"` into `&#34;` and `'` into `&#39;`, so the browser shows the characters instead of treating them as markup. Jinja2 does this automatically for Flask's `.html` templates. The lesson's stored-XSS test saves `<script>alert(1)</script>` as a note and checks that the page shows it as harmless text.

## Where it appears

| Path | What it does |
| --- | --- |
| `src/notes_app/interfaces/http/templates/base.html` | The shared page frame: header, sign-out form, content block. |
| `templates/login.html`, `signup.html`, `notes.html`, `note.html`, `error.html` | Pages that extend the frame. |
| `src/notes_app/interfaces/http/static/style.css` | The one stylesheet; the Content-Security-Policy allows only this. |
| `tests/security/test_injection.py` | Proves the encoding. |

## How it works underneath

1. Flask calls `render_template("note.html", note=note, error=None)`.
2. Jinja2 finds the file (cached after the first load), compiles it into a Python function, and calls it with the variables you gave plus the **context processor** values.
3. `{{ expression }}` prints a value. With autoescaping on, `&`, `<`, `>`, `'` and `"` in the printed text become `&amp;`, `&lt;`, `&gt;`, `&#39;`, `&#34;`.
4. `{% statement %}` is logic: `if`, `for`, `block`, `extends`.
5. The result is a plain string of HTML sent as the response body.

Autoescape is on by default for templates whose names end in `.html`, `.htm`, `.xml` or `.xhtml` when you use Flask's `render_template`.

### Ideas you need first

- **HTML.** The markup language of web pages: text with tags such as `<h1>Title</h1>` (a heading) and `<form>`. The browser draws the page from it.
- **A template.** An HTML file with holes that the server fills in for each request.
- **Escaping.** Replacing characters that have a special meaning in HTML (`<`, `>`, `&`, quotes) with harmless codes (`&lt;`, `&gt;`, `&amp;`) so user text cannot become markup.
- **A block and inheritance.** A base template defines named blocks (`{% block content %}`); child templates `extend` it and fill the blocks.

## Walkthrough of this repository's use

### Inheritance: one frame, many pages

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Notes{% endblock %}</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
```
`<!doctype html>` selects standards mode. `lang="en"` helps screen readers. `charset="utf-8"` is how the browser decodes bytes. `viewport` makes the page fit a phone screen. `{% block title %}Notes{% endblock %}` is a hole with a default; child pages override it. The stylesheet comes from the app's own `/static/` path, which the CSP (`style-src 'self'`) allows. There is no `<script>` anywhere, and the CSP forbids one.

```html
{% if current_user %}
<form method="post" action="/logout" class="inline">
  <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
  <span>Signed in as {{ current_user.username }}</span>
  <button type="submit">Sign out</button>
</form>
{% endif %}
```
`current_user` and `csrf_token` come from the context processor in `app.py` (`template_context`), which looks up the user of the current session. Sign-out is a POST form with the CSRF token as a hidden field, so a hostile site cannot log you out by showing you an image link. `{{ current_user.username }}` is autoescaped.

### Child pages

Every other page starts with `{% extends "base.html" %}` and fills `{% block title %}` and `{% block content %}`; the frame, header and sign-out form come from the base.

### `notes.html`: loops and the empty case

```html
{% for item in notes %}
<li><a href="/notes/{{ item.note.id }}">{{ item.note.title }}</a>
  <small>{% if item.role.value == "owner" %}yours{% else %}shared by {{ item.owner_username }}{% endif %}</small></li>
{% else %}
<li>No notes yet.</li>
{% endfor %}
```
`{% for ... %}{% else %}` runs the `else` part when the list is empty. `item.note.title` is user input and is escaped on output. The id is an integer from the database.

### `note.html`: the note body

```html
<pre class="note-content">{{ note.content }}</pre>
```
`<pre>` keeps line breaks. The content may contain `<script>`; autoescaping prints `&lt;script&gt;` and the browser shows the characters instead of running them. This is the exact line the weakness `UNSAFE_RAW_NOTE_OUTPUT` attacks: `app.jinja_env.autoescape = False` turns the encoding off and the stored-XSS test fails.

```html
{% if current_user and current_user.id == note.owner_id %}
<form method="post" action="/notes/{{ note.id }}/shares">
```
The share form is shown only to the owner. That is for convenience only; the server also refuses a non-owner share (`NoteService.share` calls `_authorize(..., Access.WRITE, ...)`). Hiding a button is not security.

### Form attributes that help validation

`required`, `maxlength="32"`, `minlength="12"`, `type="password"`, `autocomplete="current-password"` and `autocomplete="new-password"` help the browser and password managers. They are not trusted: the server validates again in `domain/validation.py`.

### The remaining templates

`login.html` and `signup.html` each extend the frame and fill the title and content blocks. `login.html` shows `{% if error %}<p class="error" role="alert">{{ error }}</p>{% endif %}` (`role="alert"` makes screen readers announce the message), then a form: `method="post" action="/login"`, a hidden input `csrf_token` whose value is `{{ csrf_token }}`, a text field `username` (`autocomplete="username"`, `required`, `maxlength="32"`), a password field (`type="password"`, `autocomplete="current-password"`, `maxlength="128"`), a submit button, and a link to `/signup`. `signup.html` is the same with `minlength` attributes (3 for the name, 12 for the password) and `autocomplete="new-password"` so password managers offer to generate one. `error.html` extends the frame, prints `{{ title }}` as the heading, the message if there is one, and a link home. `notes.html` loops over the notes (empty list: "No notes yet.") and has a creation form with `title` (`maxlength="120"`) and a `textarea` for `content` (`rows="6"`, `maxlength="10000"`). The form attributes only help honest users and password managers; the server validates every value again.

### Line by line: `src/notes_app/interfaces/http/templates/base.html`

A **template** is an HTML file with holes. Jinja2 fills the holes with values and sends the finished HTML to the browser. Text in `{{ ... }}` is replaced by a value; text in `{% ... %}` is an instruction (`if`, `for`, `block`). Flask's template engine **encodes** every `{{ value }}` for HTML (for example `<` becomes `&lt;`), so text typed by a user shows as text and cannot run as script. `base.html` is the page frame that every other page extends.

```html
<!doctype html>
<html lang="en">
```

`<!doctype html>` tells the browser this is modern HTML; `<html lang="en">` declares the page language.

```html
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
```

The `<head>` holds information about the page. `<meta charset="utf-8">` sets the text encoding; the `viewport` meta makes the page fit phone screens.

```html
  <title>{% block title %}Notes{% endblock %}</title>
```

`<title>` is the text on the browser tab. `{% block title %}Notes{% endblock %}` defines a **block**: a named hole that child templates can replace. The text inside is the default.

```html
  <link rel="stylesheet" href="/static/style.css">
</head>
```

`<link rel="stylesheet" href="/static/style.css">` loads the stylesheet from the site itself, which the content security policy allows (`style-src 'self'`). There is no script tag anywhere.

```html
<body>
  <header>
    <a class="brand" href="/">Notes</a>
```

`<body>` is what is shown. The `<header>` holds a link `class="brand"` to the home page.

```html
    {% if current_user %}
    <form method="post" action="/logout" class="inline">
      <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
      <span>Signed in as {{ current_user.username }}</span>
      <button type="submit">Sign out</button>
    </form>
    {% endif %}
```

`{% if current_user %}` shows a sign-out form only for a signed-in user. The form posts to `/logout`. The hidden input `csrf_token` carries the session's CSRF token (`{{ csrf_token }}`) so the server accepts the post. The form shows the username and a submit button.

```html
  </header>
  <main>
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

The `<main>` area holds `{% block content %}{% endblock %}`, the hole each page fills. The tags are then closed.

### Line by line: `src/notes_app/interfaces/http/templates/error.html`

```html
{% extends "base.html" %}
{% block title %}{{ title }}{% endblock %}
{% block content %}
```

`{% extends "base.html" %}` says this page is the base page with some blocks replaced. The title block is set to the error's title, and the content block starts.

```html
<h1>{{ title }}</h1>
{% if message %}<p>{{ message }}</p>{% endif %}
<p><a href="/">Home</a></p>
{% endblock %}
```

A heading with the title, a paragraph with the message only `{% if message %}`, and a link home. `{% endblock %}` closes the content block.

### Line by line: `src/notes_app/interfaces/http/templates/login.html`

```html
{% extends "base.html" %}
{% block title %}Sign in{% endblock %}
{% block content %}
<h1>Sign in</h1>
```

Extends the base; the tab title is "Sign in" and the page heading is "Sign in".

```html
{% if error %}<p class="error" role="alert">{{ error }}</p>{% endif %}
```

If the route passed an `error`, a paragraph shows it. `class="error"` styles it and `role="alert"` makes screen readers announce it.

```html
<form method="post" action="/login">
  <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
```

A form that posts to `/login`, with the hidden CSRF token.

```html
  <label>Username <input name="username" autocomplete="username" required maxlength="32"></label>
  <label>Password <input name="password" type="password" autocomplete="current-password" required maxlength="128"></label>
```

Two labelled fields. `autocomplete="username"` and `"current-password"` let password managers fill them; `required` stops an empty submit; `maxlength` limits the length in the browser (32 and 128, matching the server's rules, which are the real check). The password field has `type="password"`, which hides what is typed.

```html
  <button type="submit">Sign in</button>
</form>
<p>New here? <a href="/signup">Create an account</a>.</p>
{% endblock %}
```

The submit button and a link to the sign-up page; the block ends.

### Line by line: `src/notes_app/interfaces/http/templates/note.html`

```html
{% extends "base.html" %}
{% block title %}{{ note.title }}{% endblock %}
{% block content %}
<h1>{{ note.title }}</h1>
```

Extends the base; the tab title and the heading are the note's title. Because of the automatic encoding, a title like `<b>x</b>` is shown as text.

```html
{% if error %}<p class="error" role="alert">{{ error }}</p>{% endif %}
```

The optional error paragraph.

```html
<pre class="note-content">{{ note.content }}</pre>
```

`<pre class="note-content">` shows the content with its line breaks kept. `{{ note.content }}` is encoded, so hostile markup in a note is inert.

```html
{% if current_user and current_user.id == note.owner_id %}
<form method="post" action="/notes/{{ note.id }}/shares">
  <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
  <label>Share with (username) <input name="username" required maxlength="32"></label>
  <button type="submit">Share</button>
</form>
{% endif %}
```

Only for the owner (`current_user.id == note.owner_id`), a form posts to `/notes/<id>/shares` with the CSRF token and a field for the username to share with.

```html
<p><a href="/notes">Back to your notes</a></p>
{% endblock %}
```

A link back to the list, and the end of the block.

### Line by line: `src/notes_app/interfaces/http/templates/notes.html`

```html
{% extends "base.html" %}
{% block title %}Your notes{% endblock %}
{% block content %}
<h1>Your notes</h1>
{% if error %}<p class="error" role="alert">{{ error }}</p>{% endif %}
```

Extends the base, with title and heading "Your notes" and the optional error paragraph.

```html
<ul class="notes">
  {% for item in notes %}
  <li><a href="/notes/{{ item.note.id }}">{{ item.note.title }}</a>
    <small>{% if item.role.value == "owner" %}yours{% else %}shared by {{ item.owner_username }}{% endif %}</small></li>
  {% else %}
  <li>No notes yet.</li>
  {% endfor %}
</ul>
```

A list. `{% for item in notes %}` repeats the `<li>` for each visible note: a link to `/notes/<id>` with the encoded title, and a small label: "yours" if the role is `owner`, else "shared by" and the owner's username. `{% else %}` after a `for` runs only when the list is empty and shows "No notes yet."

```html
<h2>New note</h2>
<form method="post" action="/notes">
  <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
  <label>Title <input name="title" required maxlength="120"></label>
  <label>Content <textarea name="content" rows="6" maxlength="10000"></textarea></label>
  <button type="submit">Save note</button>
</form>
```

The "New note" form posts to `/notes` with the CSRF token, a required title (at most 120 characters) and a content text area of six rows (at most 10,000 characters).

```html
{% endblock %}
```

The block ends.

### Line by line: `src/notes_app/interfaces/http/templates/signup.html`

```html
{% extends "base.html" %}
{% block title %}Create an account{% endblock %}
{% block content %}
<h1>Create an account</h1>
{% if error %}<p class="error" role="alert">{{ error }}</p>{% endif %}
```

Extends the base, with the heading "Create an account" and the optional error paragraph.

```html
<form method="post" action="/signup">
  <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
```

A form that posts to `/signup`, with the CSRF token.

```html
  <label>Username <input name="username" autocomplete="username" required minlength="3" maxlength="32"></label>
  <label>Password (12 to 128 characters) <input name="password" type="password" autocomplete="new-password" required minlength="12" maxlength="128"></label>
```

Username (3 to 32 characters, `autocomplete="username"`) and password (12 to 128 characters, `autocomplete="new-password"`, which tells password managers to offer a new password).

```html
  <button type="submit">Create account</button>
</form>
<p>Already registered? <a href="/login">Sign in</a>.</p>
{% endblock %}
```

The submit button, a link to sign-in, and the end of the block.

## Try it yourself

1. See escaping directly:
   ```bash
   .venv/bin/python - <<'EOF'
   from jinja2 import Environment
   print(Environment(autoescape=True).from_string("{{ x }}").render(x="<script>alert(1)</script>"))
   print(Environment(autoescape=False).from_string("{{ x }}").render(x="<b>"))
   EOF
   ```
   Expect `&lt;script&gt;alert(1)&lt;/script&gt;` and then `<b>`.
2. Mark text safe on purpose (what to avoid):
   ```bash
   .venv/bin/python -c "from markupsafe import Markup; print(Markup('<b>hi</b>'), Markup.escape('<b>hi</b>'))"
   ```
   Expect `<b>hi</b> &lt;b&gt;hi&lt;/b&gt;`.
3. Run the injection tests (needs `make up` for the database):
   ```bash
   .venv/bin/pytest tests/security/test_injection.py -v
   ```
   Expect 4 passed.
4. Prove the control (needs `make up`):
   ```bash
   make prove
   ```
   Look for `UNSAFE_RAW_NOTE_OUTPUT` followed by `FAILS without the control (proven)`.

## Mistakes people make

- `{{ value|safe }}` or `Markup(user_text)` on user text. The repository never uses either.
- Putting user input inside a `<script>` block or an `on...=` attribute, where HTML escaping is not enough. The templates contain no script and no inline handlers.
- Building HTML with string concatenation in Python. All HTML is in templates.
- Trusting `maxlength` and `required` as validation.
- Turning autoescape off globally "to fix a display problem".

## Check yourself

1. What does autoescaping do to `<` in a printed value?
   *It prints `&lt;`, so the browser shows the character and does not start a tag.*
2. Why is the share form hidden from non-owners, and why is that not the security control?
   *It is a convenience; the server checks ownership on every request.*
3. Where do `csrf_token` and `current_user` come from?
   *The `template_context` context processor in `app.py`.*
4. What is `{% block %}` for?
   *A named hole in a base template that child templates fill.*
5. Which weakness switch turns off output encoding?
   *`UNSAFE_RAW_NOTE_OUTPUT` (only accepted with `APP_ENV=test`).*

## Further reading

- Jinja 3.1 template designer: https://jinja.palletsprojects.com/en/3.1.x/templates/
- Autoescaping in Flask: https://flask.palletsprojects.com/en/stable/templating/#controlling-autoescaping
- HTML reference (MDN): https://developer.mozilla.org/en-US/docs/Web/HTML
- OWASP XSS prevention cheat sheet: https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html
