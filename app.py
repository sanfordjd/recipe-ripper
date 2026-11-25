"""Private recipe collection with URL import and a review step."""

import functools
import hmac
import html
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import ssl
import threading
import time
from datetime import timedelta
from decimal import Decimal
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer
from werkzeug.security import check_password_hash


ROOT = Path(__file__).resolve().parent
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / '.venv' / 'browsers'))
FIELDS = ('title', 'servings', 'prep_time', 'cook_time', 'total_time',
          'source_url', 'ingredients', 'steps')
MAX_PAGE = 2 * 1024 * 1024
MAX_PASTED_TEXT = 200000
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get('APP_SECRET_KEY'),
    PASSWORD_HASH=os.environ.get('APP_PASSWORD_HASH', ''),
    DATABASE=os.environ.get('DATABASE_PATH', str(ROOT / 'recipes.sqlite3')),
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE', '1') != '0',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)
if os.environ.get('TRUSTED_HOSTS'):
    app.config['TRUSTED_HOSTS'] = os.environ['TRUSTED_HOSTS'].split(',')

attempts = {}
attempt_lock = threading.Lock()
browser_slots = threading.BoundedSemaphore(1)


class ImportProblem(ValueError):
    """A URL or page cannot be imported."""


def clean(value):
    """Convert page content to plain text without rendering its HTML."""
    if value is None:
        return ''
    if isinstance(value, list):
        return ', '.join(filter(None, (clean(item) for item in value)))
    if isinstance(value, dict):
        return clean(value.get('text') or value.get('name') or '')
    soup = BeautifulSoup(str(value), 'html.parser')
    for unwanted in soup(['script', 'style']):
        unwanted.decompose()
    return ' '.join(html.unescape(soup.get_text(' ', strip=True)).split())


def duration(value):
    text = clean(value)
    match = re.fullmatch(r'P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?', text)
    if not match or not any(match.groups()):
        return text
    units = ('day', 'hour', 'minute', 'second')
    return ' '.join(f'{amount} {unit}{"s" if float(amount) != 1 else ""}'
                    for amount, unit in zip(match.groups(), units) if amount and float(amount))


def format_total_time(value):
    """Express known total durations in hours, minutes, and seconds."""
    text = clean(value)
    note_match = re.fullmatch(r'(.*?)(\s*\([^()]*\))?', text)
    core = note_match.group(1).strip()
    note = (note_match.group(2) or '').strip()
    iso = re.fullmatch(r'P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?', core, re.IGNORECASE)
    quantities = []
    if iso and any(iso.groups()):
        quantities = [(amount, unit) for amount, unit in zip(iso.groups(), ('d', 'h', 'm', 's')) if amount is not None]
    else:
        matches = list(re.finditer(r'(\d+(?:\.\d+)?)\s*(days?|d|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b', core, re.IGNORECASE))
        cursor = 0
        for match in matches:
            if not re.fullmatch(r'[\s,]*(?:and[\s,]*)?', core[cursor:match.start()], re.IGNORECASE):
                return text
            quantities.append((match.group(1), match.group(2).lower()[0]))
            cursor = match.end()
        if not matches or core[cursor:].strip():
            return text
    try:
        seconds = sum((Decimal(amount) * {'d': 86400, 'h': 3600, 'm': 60, 's': 1}[unit] for amount, unit in quantities), Decimal(0))
        hours, remainder = divmod(seconds, Decimal(3600))
        minutes, seconds = divmod(remainder, Decimal(60))
    except ArithmeticError:
        return text
    parts = []
    for amount, unit in ((hours, 'hour'), (minutes, 'minute'), (seconds, 'second')):
        if amount:
            number = format(amount, 'f')
            if '.' in number:
                number = number.rstrip('0').rstrip('.')
            parts.append(f'{number} {unit}{"s" if amount != 1 else ""}')
    result = ' '.join(parts) or '0 minutes'
    return f'{result} {note}' if note else result


app.add_template_filter(format_total_time, 'total_time')


def sentence_lines(paragraph):
    """Put sentences on separate lines without splitting decimal numbers."""
    text = ' '.join(paragraph.split())
    sentences, start = [], 0
    for boundary in re.finditer(r'[.!?]+[\"\u201d\x27\u2019)\]]*\s+', text):
        before = text[:boundary.start() + 1]
        after = text[boundary.end():]
        abbreviation = re.search(r'\b(tsp|tbsp|oz|lb|lbs|min|mins|hr|hrs|approx|e\.g|i\.e|etc)\.$', before, re.IGNORECASE)
        if abbreviation:
            next_letter = after.lstrip('\"\u201c\x27\u2018([')[:1]
            if abbreviation.group(1).lower() in ('e.g', 'i.e', 'approx') or next_letter.islower() or next_letter.isdigit():
                continue
        if re.fullmatch(r'\d+\.', before):
            continue
        sentences.append(text[start:boundary.end()].strip())
        start = boundary.end()
    if text[start:].strip():
        sentences.append(text[start:].strip())
    return '\n'.join(sentences)


def format_steps(value, legacy=False):
    """Separate sentences with newlines and step paragraphs with blank lines."""
    text = str(value or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if not text:
        return ''
    if legacy and not re.search(r'\n\s*\n', text):
        paragraphs = text.splitlines()
    else:
        paragraphs = re.split(r'\n\s*\n', text)
    return '\n\n'.join(sentence_lines(paragraph) for paragraph in paragraphs if paragraph.strip())


def recipe_steps(recipe):
    formatted = format_steps(recipe.get('steps', ''), legacy=recipe.get('_steps_format') != 'sentences-v1')
    return formatted.split('\n\n') if formatted else []


app.add_template_filter(recipe_steps, 'step_paragraphs')


def instruction_lines(value):
    if isinstance(value, str):
        return [line for part in value.splitlines() if (line := clean(part))]
    if isinstance(value, list):
        return [line for part in value for line in instruction_lines(part)]
    if isinstance(value, dict):
        if value.get('itemListElement'):
            lines = instruction_lines(value['itemListElement'])
            heading = clean(value.get('name'))
            if heading and lines:
                lines[0] = f'{heading}: {lines[0]}'
            return lines
        text = clean(value.get('text') or value.get('name'))
        return [text] if text else []
    return []


def pasted_line(value):
    """Remove common chat Markdown while keeping recipe text and links."""
    text = re.sub(r'^\s*#{1,6}\s*', '', value).strip()
    text = re.sub(r'^\s*(?:[-*+•]\s+|\d+[.)]\s+)', '', text)
    text = text.replace('**', '').replace('__', '').replace('`', '')
    text = re.sub(r'(?<!\w)\*([^*]+)\*(?!\w)', r'\1', text)
    return clean(text).strip('* ').strip()


def pasted_metadata(line, recipe):
    labels = {
        'title': 'title', 'recipe title': 'title', 'recipe': 'title',
        'servings': 'servings', 'serves': 'servings', 'serving size': 'servings',
        'yield': 'servings', 'makes': 'servings',
        'prep': 'prep_time', 'prep time': 'prep_time',
        'preparation time': 'prep_time', 'cook': 'cook_time',
        'cook time': 'cook_time', 'cooking time': 'cook_time',
        'total': 'total_time', 'total time': 'total_time',
        'source': 'source_url', 'source url': 'source_url',
        'source link': 'source_url', 'original recipe': 'source_url',
    }
    label_pattern = '|'.join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
    matches = list(re.finditer(r'(?<!\w)(' + label_pattern + r')\s*:\s*', line, re.IGNORECASE))
    if matches and line[:matches[0].start()].strip(' |•'):
        return False
    if not matches:
        serving = re.fullmatch(r'(serves|servings|makes|yield)\s+(.+)', line, re.IGNORECASE)
        if serving:
            recipe['servings'] = serving.group(2).strip()
            return True
        return False
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
        value = line[match.end():end].strip(' |•')
        field = labels[match.group(1).lower()]
        if field == 'source_url':
            link = re.search(r'https?://[^\s<>]+', value)
            if link:
                url = link.group().rstrip(').,]')
                try:
                    validate_url(url)
                except ImportProblem:
                    continue
                recipe[field] = url
        else:
            recipe[field] = value
    return True


def extract_pasted_recipe(text, source_url=''):
    """Separate a complete Markdown or plain-text recipe response."""
    recipe = dict.fromkeys(FIELDS, '')
    ingredients, steps, titles = [], [], []
    section = None
    paragraph_break = True
    pending_step_heading = ''
    for raw in text.replace('\r\n', '\n').replace('\r', '\n').splitlines():
        if re.fullmatch(r'\s*(?:`{3,}.*|~{3,}.*|[-*_]{3,})\s*', raw):
            continue
        line = pasted_line(raw)
        if not line:
            paragraph_break = True
            continue
        if re.fullmatch(r'(jump to recipe|print recipe|save recipe|cook mode|prevent your screen from going dark|keep screen awake|[123]x|us customary|metric|us customary metric)', line, re.IGNORECASE):
            continue
        if re.match(r'^(let me know\b|would you like\b|if you[\u2019\x27]d like\b|i can\b|enjoy[.!]?$)', line, re.IGNORECASE):
            section = 'other'
            continue
        if pasted_metadata(line, recipe):
            continue
        heading, separator, inline = line.partition(':')
        heading = heading.strip().lower()
        section_match = re.fullmatch(r'(ingredients(?: list)?|what you(?:\u2019|\x27)ll need|instructions|directions|method|steps(?: to make it)?|preparation|procedure|how to make)(?:\s*\([^)]*\))?', heading)
        if section_match:
            name = section_match.group(1)
            section = 'ingredients' if name.startswith(('ingredients', 'what you')) else 'steps'
            paragraph_break = True
            pending_step_heading = ''
            if not separator or not inline.strip():
                continue
            line = pasted_line(inline)
            raw = inline
        elif re.fullmatch(r'(notes?(?: and tips)?|tips(?: and notes)?|storage(?: and reheating)?|variations|nutrition(?:al information| facts)?|serving suggestions|equipment|substitutions|troubleshooting|optional additions|rate this recipe|recipe ratings|related recipes|you may also like|comments|reviews)', heading):
            section = 'other'
            continue
        marked_heading = bool(re.match(r'^\s*#{1,6}\s', raw) or re.fullmatch(r'\s*\*\*.+\*\*\s*', raw))
        bullet = bool(re.match(r'^\s*(?:[-*+•]\s+|\d+[.)]\s+)', raw))
        step_label = re.match(r'^step\s+\d+\s*[:.)-]\s*(.*)', line, re.IGNORECASE)
        if section == 'ingredients':
            if raw[:1].isspace() and not bullet and not marked_heading and ingredients and not paragraph_break:
                ingredients[-1] += ' ' + line
            else:
                ingredients.append(line)
        elif section == 'steps':
            if re.fullmatch(r'step\s+\d+', line, re.IGNORECASE):
                paragraph_break = True
                continue
            if step_label:
                line = step_label.group(1)
                if marked_heading and line and not line.endswith(('.', '!', '?', ':')):
                    line += ':'
                bullet = True
            elif marked_heading:
                pending_step_heading = line.rstrip(':')
                paragraph_break = True
                continue
            if pending_step_heading:
                line = pending_step_heading + ': ' + line
                pending_step_heading = ''
            if bullet or paragraph_break or not steps:
                steps.append(line)
            else:
                steps[-1] += ' ' + line
        elif section is None:
            if re.fullmatch(r'(skip to (?:main )?content|menu|search|home|recipes|news|about us|contact us|sign in|log in|subscribe|newsletter)', line, re.IGNORECASE):
                continue
            if re.match(r'^(by\s|updated\s|published\s|reviewed by\s|tested by\s|\d+(?:\.\d+)?\s*(?:ratings?|reviews?)\b)', line, re.IGNORECASE):
                continue
            if re.match(r'^(sure\b|here\b|here[\u2019\x27]s\b|absolutely\b|of course\b|user:|assistant:|claude:|codex:)', line, re.IGNORECASE):
                continue
            if marked_heading or (len(line) <= 160 and len(line.split()) <= 20 and not line.endswith(('.', '!', '?'))):
                titles.append((marked_heading, line))
        paragraph_break = False
    if not recipe['title'] and titles:
        marked = [title for is_marked, title in titles if is_marked]
        recipe['title'] = marked[-1] if marked else titles[0][1]
        source = source_url or recipe['source_url']
        if source:
            slug = unquote(urlsplit(source).path.rstrip('/').rsplit('/', 1)[-1])
            words = set(re.findall(r'[a-z]{3,}', slug.lower())) - {'recipe', 'recipes'}
            scored = [(len(words & set(re.findall(r'[a-z]{3,}', title.lower()))), title) for _, title in titles]
            best_score = max((score for score, _ in scored), default=0)
            if words and best_score >= min(2, len(words)):
                recipe['title'] = next(title for score, title in scored if score == best_score)
    recipe['ingredients'] = '\n'.join(ingredients)
    recipe['steps'] = format_steps('\n\n'.join(steps))
    recipe['_steps_format'] = 'sentences-v1'
    recipe['total_time'] = format_total_time(recipe['total_time'])
    return recipe


def json_nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from json_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from json_nodes(child)


def extract_recipes(page, source_url):
    """Read Recipe objects from JSON-LD and standard HTML microdata."""
    soup = BeautifulSoup(page, 'html.parser')
    nodes = []
    for script in soup.find_all('script'):
        if str(script.get('type', '')).lower().split(';')[0].strip() != 'application/ld+json':
            continue
        try:
            data = json.loads(script.string or script.get_text())
            for node in json_nodes(data):
                types = node.get('@type', [])
                types = types if isinstance(types, list) else [types]
                if any(str(kind).rstrip('/').split('/')[-1] == 'Recipe' for kind in types):
                    nodes.append(node)
        except (ValueError, RecursionError):
            continue
    if not nodes:
        for scope in soup.select('[itemscope][itemtype]'):
            if not any(kind.rstrip('/').endswith('/Recipe') for kind in scope['itemtype'].split()):
                continue
            node = {}
            for prop in scope.select('[itemprop]'):
                owner = prop.find_parent(attrs={'itemscope': True})
                if owner is not scope:
                    continue
                for key in prop['itemprop'].split():
                    if key in ('name', 'recipeYield', 'prepTime', 'cookTime', 'totalTime', 'recipeIngredient', 'recipeInstructions'):
                        value = prop.get('content') or prop.get('datetime') or prop.get_text(' ', strip=True)
                        node.setdefault(key, []).append(value)
            nodes.append(node)
    recipes, seen = [], set()
    for node in nodes:
        ingredients = node.get('recipeIngredient', [])
        if isinstance(ingredients, str):
            ingredients = ingredients.splitlines()
        if not isinstance(ingredients, list):
            ingredients = []
        recipe = dict(
            title=clean(node.get('name')), servings=clean(node.get('recipeYield')),
            prep_time=duration(node.get('prepTime')), cook_time=duration(node.get('cookTime')),
            total_time=format_total_time(node.get('totalTime')), source_url=source_url,
            ingredients='\n'.join(filter(None, (clean(item) for item in ingredients))),
            steps=format_steps('\n\n'.join(instruction_lines(node.get('recipeInstructions', [])))),
            _steps_format='sentences-v1',
        )
        fingerprint = (recipe['title'], recipe['ingredients'], recipe['steps'])
        if recipe['title'] and (recipe['ingredients'] or recipe['steps']) and fingerprint not in seen:
            seen.add(fingerprint)
            recipes.append(recipe)
    return recipes


def validate_url(value):
    """Allow ordinary HTTP(S) URLs with no credentials or unusual ports."""
    value = value.strip()
    if len(value) > 4096 or any(ord(char) < 32 for char in value) or '\\' in value:
        raise ImportProblem('Enter a valid recipe URL.')
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        if port != (443 if parsed.scheme == 'https' else 80):
            raise ValueError
        host = parsed.hostname.rstrip('.').encode('idna').decode('ascii')
        if not host:
            raise ValueError
    except (ValueError, UnicodeError):
        raise ImportProblem('Use an http:// or https:// recipe URL without a username or port.') from None
    return parsed, host, port


def public_addresses(host, port):
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise ImportProblem('The website address could not be found.') from None
    if not addresses:
        raise ImportProblem('The website address could not be found.')
    for _, _, _, _, address in addresses:
        ip = ipaddress.ip_address(address[0])
        if not ip.is_global or getattr(ip, 'ipv4_mapped', None) is not None:
            raise ImportProblem('Only public websites can be imported.')
    return addresses


def fetch_public_response(url, headers=None, deadline=None):
    """Fetch one response through an IP-checked connection with verified TLS."""
    deadline = deadline if deadline is not None else time.monotonic() + 25
    parsed, host, port = validate_url(url)
    addresses = public_addresses(host, port)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ImportProblem('The website took too long to respond.')
    family, kind, protocol, _, address = addresses[0]
    connection, sock = None, None
    try:
        sock = socket.socket(family, kind, protocol)
        sock.settimeout(min(remaining, 8))
        sock.connect(address)
        if parsed.scheme == 'https':
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        connection = http.client.HTTPConnection(host, port, timeout=min(remaining, 8))
        connection.sock = sock
        request_headers = {key: value for key, value in (headers or {}).items()
                           if key.lower() not in ('host', 'connection', 'content-length', 'accept-encoding',
                                                  'proxy-authorization', 'proxy-connection', 'upgrade')}
        request_headers['Host'] = f'[{host}]' if ':' in host else host
        request_headers['Accept-Encoding'] = 'identity'
        target = urlunsplit(('', '', parsed.path or '/', parsed.query, ''))
        connection.request('GET', target, headers=request_headers)
        response = connection.getresponse()
        if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
            raise ImportProblem('The website returned an unsupported page encoding.')
        response_headers = {}
        for key, value in response.getheaders():
            key = key.lower()
            if key in response_headers:
                separator = '\n' if key == 'set-cookie' else ', '
                response_headers[key] += separator + value
            else:
                response_headers[key] = value
        chunks, size = [], 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ImportProblem('The website took too long to respond.')
            sock.settimeout(min(remaining, 8))
            chunk = response.read1(min(65536, MAX_PAGE + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_PAGE:
                raise ImportProblem('This page is too large to import.')
            chunks.append(chunk)
        return response.status, response_headers, b''.join(chunks)
    except ImportProblem:
        raise
    except (OSError, http.client.HTTPException, UnicodeError, ValueError):
        raise ImportProblem('The website could not be reached securely.') from None
    finally:
        if connection:
            connection.close()
        elif sock:
            sock.close()


def fetch_page(url):
    """Read HTML, rechecking public addresses at every redirect."""
    deadline = time.monotonic() + 25
    for _ in range(6):
        status, headers, body = fetch_public_response(url, headers={
            'User-Agent': 'RecipeRipper/1.0 (personal recipe importer)',
            'Accept': 'text/html,application/xhtml+xml',
        }, deadline=deadline)
        if status in (301, 302, 303, 307, 308):
            if not headers.get('location'):
                raise ImportProblem('The website returned an incomplete redirect.')
            url = urljoin(url, headers['location'])
            continue
        if status in (401, 403, 429):
            raise ImportProblem(f'The website restricted the standard import (HTTP {status}).')
        if status != 200:
            raise ImportProblem(f'The website returned HTTP {status}.')
        if not any(kind in headers.get('content-type', '').lower() for kind in ('text/html', 'application/xhtml+xml')):
            raise ImportProblem('That URL did not return a web page.')
        return body
    raise ImportProblem('The website redirected too many times.')


def visible_page_text(url):
    """Render a public page and read its text for the automatic second try."""
    _, host, port = validate_url(url)
    public_addresses(host, port)
    try:
        from playwright.sync_api import Error as BrowserError
        from playwright.sync_api import TimeoutError as BrowserTimeout
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ImportProblem('The automatic browser is not installed.') from None
    if not browser_slots.acquire(timeout=1):
        raise ImportProblem('The automatic browser is busy. Try importing again shortly.')
    deadline = time.monotonic() + 30
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, timeout=10000,
                                                  args=['--host-resolver-rules=MAP * ~NOTFOUND'])
            try:
                context = browser.new_context(service_workers='block', accept_downloads=False)
                context.route_web_socket('**/*', lambda route: route.close())
                context.add_init_script("""for (const name of ['RTCPeerConnection', 'webkitRTCPeerConnection', 'WebTransport']) {
                    Object.defineProperty(window, name, {value: undefined, configurable: false, writable: false})
                }""")
                page = context.new_page()
                requests_seen, bytes_seen = 0, 0

                def handle_request(route):
                    nonlocal requests_seen, bytes_seen
                    requests_seen += 1
                    req = route.request
                    if (req.method != 'GET' or req.resource_type in ('image', 'media', 'font')
                            or requests_seen > 100 or bytes_seen >= 8 * MAX_PAGE
                            or time.monotonic() >= deadline):
                        route.abort()
                        return
                    if req.resource_type == 'document' and req.frame != page.main_frame:
                        route.abort()
                        return
                    try:
                        status, headers, body = fetch_public_response(req.url,
                                                                      headers=req.all_headers(), deadline=deadline)
                        bytes_seen += len(body)
                        if bytes_seen > 8 * MAX_PAGE:
                            route.abort()
                            return
                        filtered = {key: value for key, value in headers.items()
                                    if key not in ('content-length', 'transfer-encoding', 'content-encoding',
                                                   'connection', 'keep-alive', 'upgrade')}
                        route.fulfill(status=status, headers=filtered, body=body)
                    except ImportProblem:
                        route.abort()

                context.route('**/*', handle_request)
                page.goto(url, wait_until='domcontentloaded', timeout=15000)
                remaining = max(1, int((deadline - time.monotonic()) * 1000))
                try:
                    page.wait_for_function("""() => document.body &&
                        /ingredients/i.test(document.body.innerText) &&
                        /instructions|directions|method|steps|preparation/i.test(document.body.innerText)""",
                                           timeout=min(8000, remaining))
                except BrowserTimeout:
                    pass
                page.evaluate("""() => {
                    for (const list of document.querySelectorAll('ol, ul')) {
                        const items = Array.from(list.children).filter(item => item.tagName === 'LI')
                        for (const [index, item] of items.entries()) {
                            if (!item.getClientRects().length || /^(?:\\d+[.)]|[-*+\u2022])\\s/.test(item.innerText.trim())) continue
                            const prefix = list.tagName === 'OL' ? `${Number(list.getAttribute('start') || 1) + index}. ` : '- '
                            item.insertAdjacentText('afterbegin', prefix)
                        }
                    }
                }""")
                remaining = max(1, int((deadline - time.monotonic()) * 1000))
                text = page.locator('body').inner_text(timeout=min(4000, remaining)).strip()
                if not text or len(text) > MAX_PASTED_TEXT:
                    raise ImportProblem('The automatic browser did not return usable recipe text.')
                return text
            finally:
                browser.close()
    except (BrowserError, OSError):
        raise ImportProblem('The background browser could not load this recipe page.') from None
    finally:
        browser_slots.release()


def database():
    connection = sqlite3.connect(app.config['DATABASE'], timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute('CREATE TABLE IF NOT EXISTS recipes (id INTEGER PRIMARY KEY, title TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
    return connection


def ready():
    secret = app.config.get('SECRET_KEY') or ''
    password_hash = app.config.get('PASSWORD_HASH') or ''
    return len(secret) >= 32 and password_hash.startswith(('scrypt:', 'pbkdf2:'))


def signed_in(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        if not session.get('signed_in'):
            return redirect(url_for('login'))
        return function(*args, **kwargs)
    return wrapped


@app.before_request
def guard():
    if not ready():
        return render_template('index.html', mode='setup'), 503
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(32)
    if request.method == 'POST':
        token = request.form.get('csrf', '')
        if not hmac.compare_digest(token.encode('utf-8'), session['csrf'].encode('utf-8')):
            abort(400, description='This form expired. Reload the page and try again.')


@app.after_request
def headers(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
    if app.config['SESSION_COOKIE_SECURE']:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    return response


@app.context_processor
def theme_settings():
    theme = request.cookies.get('theme', 'dark')
    return {'theme': theme if theme in ('dark', 'light') else 'dark'}


@app.post('/theme')
def set_theme():
    theme = request.form.get('theme', '')
    if theme not in ('dark', 'light'):
        abort(400)
    target = request.form.get('return_to', '/')
    if (len(target) > 4096 or not target.startswith('/') or target.startswith('//')
            or '\\' in target or any(ord(char) < 32 for char in target)):
        target = '/'
    screen = request.form.get('screen', '')
    if screen in ('editor', 'choose', 'paste', 'all_recipes', 'delete_many'):
        if not session.get('signed_in'):
            return redirect(url_for('login'))
        if screen == 'editor':
            recipe = {key: request.form.get(key, '') for key in FIELDS}
            recipe['steps'] = format_steps(recipe['steps'], legacy=request.form.get('steps_format') != 'sentences-v1')
            recipe['_steps_format'] = 'sentences-v1'
            recipe_id = request.form.get('recipe_id', '')
            if recipe_id:
                if not recipe_id.isdecimal():
                    abort(400)
                recipe['id'] = int(recipe_id)
            response = app.make_response(render_template('index.html', mode='editor', recipe=recipe, theme=theme,
                                                        original_text=request.form.get('original_text', '')))
        elif screen == 'paste':
            source = checked_paste_source(request.form.get('fallback_source_url', ''))
            response = app.make_response(render_template('index.html', mode='paste', theme=theme,
                                                        pasted_text=request.form.get('recipe_text', ''),
                                                        fallback_source_url=source))
        elif screen == 'all_recipes':
            selected = recipe_selection(request.form.getlist('recipe_ids'), allow_empty=True)
            response = app.make_response(render_template('index.html', mode='all_recipes',
                                                        recipes=recipe_titles(), selected_ids=selected, theme=theme))
        elif screen == 'delete_many':
            confirmation_token = request.form.get('confirmation_token', '')
            selected = confirmed_selection(confirmation_token)
            response = app.make_response(render_template('index.html', mode='delete_many',
                                                        recipes=selected_titles(selected),
                                                        confirmation_token=confirmation_token, theme=theme))
        else:
            try:
                drafts = json.loads(request.form.get('drafts', '[]'))
                if not isinstance(drafts, list) or not 1 <= len(drafts) <= 20 or not all(isinstance(item, dict) for item in drafts):
                    raise ValueError
                recipes = []
                for item in drafts:
                    recipe = {key: str(item.get(key, '')) for key in FIELDS}
                    recipe['steps'] = format_steps(recipe['steps'], legacy=item.get('_steps_format') != 'sentences-v1')
                    recipe['_steps_format'] = 'sentences-v1'
                    recipes.append(recipe)
            except (ValueError, TypeError):
                abort(400)
            response = app.make_response(render_template('index.html', mode='choose', recipes=recipes, theme=theme))
    else:
        response = redirect(target)
    response.set_cookie('theme', theme, max_age=31536000,
                        secure=app.config['SESSION_COOKIE_SECURE'],
                        httponly=True, samesite='Lax')
    return response


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        now = time.monotonic()
        key = request.remote_addr or 'unknown'
        with attempt_lock:
            for address in list(attempts):
                attempts[address] = [stamp for stamp in attempts[address] if now - stamp < 600]
                if not attempts[address]:
                    del attempts[address]
            recent = attempts.setdefault(key, [])
            blocked = len(recent) >= 10
            if not blocked:
                recent.append(now)
        if blocked:
            return render_template('index.html', mode='login', error='Too many sign-in attempts. Wait ten minutes and try again.'), 429
        password = request.form.get('password', '')
        if len(password) <= 1024 and check_password_hash(app.config['PASSWORD_HASH'], password):
            session.clear()
            session['signed_in'] = True
            session['csrf'] = secrets.token_urlsafe(32)
            session.permanent = True
            return redirect(url_for('collection'))
        return render_template('index.html', mode='login', error='The password did not match.'), 401
    return render_template('index.html', mode='login')


@app.post('/logout')
@signed_in
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.get('/')
@signed_in
def collection():
    query = request.args.get('q', '').strip()[:200]
    connection = database()
    try:
        rows = connection.execute('SELECT id, title, payload FROM recipes WHERE title LIKE ? ORDER BY id DESC', (f'%{query}%',)).fetchall()
    finally:
        connection.close()
    recipes = [dict(json.loads(row['payload']), id=row['id']) for row in rows]
    return render_template('index.html', mode='collection', recipes=recipes, query=query)


def recipe_titles():
    connection = database()
    try:
        rows = connection.execute('SELECT id, title FROM recipes ORDER BY title COLLATE NOCASE, id').fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def recipe_selection(values, allow_empty=False):
    selected = []
    for value in values:
        text = str(value)
        if not text.isascii() or not text.isdecimal() or len(text) > 19 or not 0 < int(text) <= 9223372036854775807:
            abort(400, description='The recipe selection is invalid. Select recipes from the list again.')
        selected.append(int(text))
    selected = list(dict.fromkeys(selected))
    if not selected and not allow_empty:
        abort(400, description='Select at least one recipe before deleting.')
    return selected


def selected_titles(selected, connection=None):
    own_connection = connection is None
    connection = connection or database()
    try:
        recipes = []
        for start in range(0, len(selected), 500):
            chunk = selected[start:start + 500]
            placeholders = ','.join('?' for _ in chunk)
            rows = connection.execute(f'SELECT id, title FROM recipes WHERE id IN ({placeholders})', chunk).fetchall()
            recipes.extend(dict(row) for row in rows)
        if len(recipes) != len(selected):
            abort(409, description='Some selected recipes are no longer available. Return to the list and select recipes again.')
        return sorted(recipes, key=lambda item: (item['title'].casefold(), item['id']))
    finally:
        if own_connection:
            connection.close()


def deletion_signer():
    return URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='recipe-bulk-delete')


def confirmed_selection(token):
    try:
        data = deletion_signer().loads(token, max_age=600)
        if not isinstance(data, dict) or not isinstance(data.get('ids'), list):
            raise ValueError
        csrf = data.get('csrf', '')
        if not isinstance(csrf, str) or not hmac.compare_digest(csrf.encode('utf-8'), session['csrf'].encode('utf-8')):
            raise ValueError
    except (BadSignature, ValueError):
        abort(400, description='This deletion confirmation expired or is invalid. Select recipes again.')
    return recipe_selection(data['ids'])


@app.get('/recipes')
@signed_in
def all_recipes():
    return render_template('index.html', mode='all_recipes', recipes=recipe_titles(), selected_ids=[])


@app.post('/recipes/delete')
@signed_in
def delete_recipes():
    if request.form.get('confirm') != 'delete':
        selected = recipe_selection(request.form.getlist('recipe_ids'))
        recipes = selected_titles(selected)
        token = deletion_signer().dumps({'ids': selected, 'csrf': session['csrf']})
        return render_template('index.html', mode='delete_many', recipes=recipes, confirmation_token=token)
    selected = confirmed_selection(request.form.get('confirmation_token', ''))
    connection = database()
    try:
        with connection:
            connection.execute('BEGIN IMMEDIATE')
            selected_titles(selected, connection=connection)
            for start in range(0, len(selected), 500):
                chunk = selected[start:start + 500]
                placeholders = ','.join('?' for _ in chunk)
                connection.execute(f'DELETE FROM recipes WHERE id IN ({placeholders})', chunk)
    finally:
        connection.close()
    flash(f'{len(selected)} recipe' + ('s' if len(selected) != 1 else '') + ' deleted.')
    return redirect(url_for('all_recipes'))


@app.post('/import')
@signed_in
def import_recipe():
    source = request.form.get('source_url', '').strip()
    blank = dict.fromkeys(FIELDS, '')
    try:
        validate_url(source)
        blank['source_url'] = source
        recipes = extract_recipes(fetch_page(source), source)
        if not recipes:
            raise ImportProblem('No recipe data was found. Enter the ingredients and steps below.')
    except ImportProblem as error:
        manual_error = str(error)
        if blank['source_url']:
            try:
                text = visible_page_text(source)
                recipe = extract_pasted_recipe(text, source_url=source)
                if not recipe['ingredients'] or not recipe['steps']:
                    raise ImportProblem('The automatic text attempt could not identify both ingredients and steps.')
                recipe['source_url'] = source
                flash('Recipe text extracted automatically after the standard import failed. Review it before saving.')
                return render_template('index.html', mode='editor', recipe=recipe, original_text=text)
            except ImportProblem as browser_error:
                manual_error += ' Automatic text extraction also failed: ' + str(browser_error)
        source_text = f'Source: {blank["source_url"]}\n\n' if blank['source_url'] else ''
        return render_template('index.html', mode='paste', pasted_text=source_text, error=manual_error,
                               fallback_source_url=blank['source_url'])
    if len(recipes) > 1:
        return render_template('index.html', mode='choose', recipes=recipes[:20])
    if not recipes[0]['ingredients'] or not recipes[0]['steps']:
        flash('Some recipe data is missing. Complete it before saving.')
    return render_template('index.html', mode='editor', recipe=recipes[0])


@app.post('/review')
@signed_in
def review():
    try:
        data = json.loads(request.form.get('draft', '{}'))
        if not isinstance(data, dict):
            raise ValueError
        recipe = {key: str(data.get(key, '')) for key in FIELDS}
        recipe['steps'] = format_steps(recipe['steps'], legacy=data.get('_steps_format') != 'sentences-v1')
        recipe['_steps_format'] = 'sentences-v1'
    except (ValueError, TypeError):
        abort(400)
    return render_template('index.html', mode='editor', recipe=recipe)


def checked_paste_source(value):
    source = value.strip()
    if source:
        try:
            validate_url(source)
        except ImportProblem:
            abort(400, description='The source link is invalid.')
    return source


@app.route('/paste', methods=['GET', 'POST'])
@signed_in
def paste_recipe():
    if request.method == 'GET':
        return render_template('index.html', mode='paste', pasted_text='')
    source = checked_paste_source(request.form.get('fallback_source_url', ''))
    text = request.form.get('recipe_text', '').strip()
    if not text or len(text) > MAX_PASTED_TEXT:
        return render_template('index.html', mode='paste', pasted_text=text,
                               fallback_source_url=source,
                               error='Type or paste recipe text of up to 200,000 characters.'), 400
    recipe = extract_pasted_recipe(text, source_url=source)
    if not recipe['ingredients'] and not recipe['steps']:
        return render_template('index.html', mode='paste', pasted_text=text,
                               fallback_source_url=source,
                               error='The recipe sections could not be identified. Include Ingredients and Instructions headings in the recipe text.'), 400
    if source:
        recipe['source_url'] = source
    missing = [label for field, label in (('title', 'title'), ('ingredients', 'ingredients'), ('steps', 'steps')) if not recipe[field]]
    if missing:
        flash('Check the pasted recipe. Missing fields: ' + ', '.join(missing) + '.')
    return render_template('index.html', mode='editor', recipe=recipe, original_text=text)


@app.get('/new')
@signed_in
def new_recipe():
    return redirect(url_for('paste_recipe'))


def saved_recipe(recipe_id):
    connection = database()
    try:
        row = connection.execute('SELECT payload FROM recipes WHERE id = ?', (recipe_id,)).fetchone()
    finally:
        connection.close()
    if row is None:
        abort(404)
    recipe = dict(json.loads(row['payload']), id=recipe_id)
    recipe['steps'] = '\n\n'.join(recipe_steps(recipe))
    recipe['_steps_format'] = 'sentences-v1'
    return recipe


@app.get('/recipes/<int:recipe_id>')
@signed_in
def view_recipe(recipe_id):
    return render_template('index.html', mode='recipe', recipe=saved_recipe(recipe_id))


@app.get('/recipes/<int:recipe_id>/edit')
@signed_in
def edit_recipe(recipe_id):
    return render_template('index.html', mode='editor', recipe=saved_recipe(recipe_id))


@app.route('/recipes/<int:recipe_id>/delete', methods=['GET', 'POST'])
@signed_in
def delete_recipe(recipe_id):
    recipe = saved_recipe(recipe_id)
    if request.method == 'GET':
        return render_template('index.html', mode='delete', recipe=recipe)
    if request.form.get('confirm') != 'delete':
        abort(400)
    connection = database()
    try:
        with connection:
            cursor = connection.execute('DELETE FROM recipes WHERE id = ?', (recipe_id,))
            if cursor.rowcount != 1:
                abort(404)
    finally:
        connection.close()
    flash('Recipe deleted.')
    return redirect(url_for('collection'))


@app.post('/save')
@signed_in
def save_recipe():
    recipe = {key: request.form.get(key, '').strip() for key in FIELDS}
    recipe_id = request.form.get('recipe_id', '', type=str)
    error = None
    if recipe_id:
        if not recipe_id.isdecimal():
            abort(400)
        saved_recipe(int(recipe_id))
        recipe['id'] = int(recipe_id)
    if not all(recipe[key] for key in ('title', 'ingredients', 'steps')):
        error = 'Add a title, ingredients, and cooking steps before saving.'
    elif any(len(recipe[key]) > (30000 if key in ('ingredients', 'steps') else 4096 if key == 'source_url' else 500) for key in FIELDS):
        error = 'One field is too long. Shorten it before saving.'
    elif recipe['source_url']:
        try:
            validate_url(recipe['source_url'])
        except ImportProblem as problem:
            error = str(problem)
    if error:
        recipe['steps'] = format_steps(recipe['steps'], legacy=request.form.get('steps_format') != 'sentences-v1')
        return render_template('index.html', mode='editor', recipe=recipe, error=error,
                               original_text=request.form.get('original_text', '')), 400
    recipe['total_time'] = format_total_time(recipe['total_time'])
    recipe['steps'] = format_steps(recipe['steps'], legacy=request.form.get('steps_format') != 'sentences-v1')
    payload = json.dumps(dict({key: recipe[key] for key in FIELDS}, _steps_format='sentences-v1'), ensure_ascii=False)
    connection = database()
    try:
        with connection:
            if recipe_id:
                connection.execute('UPDATE recipes SET title = ?, payload = ? WHERE id = ?', (recipe['title'], payload, int(recipe_id)))
                record_id = int(recipe_id)
            else:
                cursor = connection.execute('INSERT INTO recipes (title, payload) VALUES (?, ?)', (recipe['title'], payload))
                record_id = cursor.lastrowid
    finally:
        connection.close()
    flash('Recipe saved.')
    return redirect(url_for('view_recipe', recipe_id=record_id))


@app.get('/export')
@signed_in
def export():
    connection = database()
    try:
        rows = connection.execute('SELECT payload FROM recipes ORDER BY id').fetchall()
    finally:
        connection.close()
    recipes = []
    for row in rows:
        stored = json.loads(row['payload'])
        recipe = {key: stored.get(key, '') for key in FIELDS}
        recipe['steps'] = '\n\n'.join(recipe_steps(stored))
        recipes.append(recipe)
    response = app.response_class(json.dumps(recipes, ensure_ascii=False, indent=2), mimetype='application/json')
    response.headers['Content-Disposition'] = 'attachment; filename=recipes.json'
    return response


@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(409)
@app.errorhandler(413)
def request_error(error):
    return render_template('index.html', mode='error', error=error.description), error.code


if __name__ == '__main__':
    from waitress import serve
    if not ready():
        raise SystemExit('Set APP_SECRET_KEY and APP_PASSWORD_HASH first. See README.md.')
    serve(app, host=os.environ.get('HOST', '127.0.0.1'), port=int(os.environ.get('PORT', '8000')), threads=4)
