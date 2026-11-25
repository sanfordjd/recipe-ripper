# Recipe Ripper

A private recipe website for a phone and computer. Paste a website URL or a complete recipe response from an AI chat, review the extracted recipe, and save it. Saved recipes contain the title, servings or yield, preparation time, cooking time, total time, source link, ingredients, and steps.

This first version uses one shared collection password. Give it only to the person who should share your collection. Both people can read, add, and edit recipes. There are no separate accounts or password reset emails.

## UI and total-time display

Dark mode is the default for a browser with no saved theme preference. Use **Light mode** or **Dark mode** in the header to switch. The preference is remembered in that browser, including after sign-out. Switching themes in the recipe editor keeps unfinished edits and does not save the recipe. Printed recipes use a light background.

Total times use hours and minutes when the duration is known. For example, `90 minutes`, `PT90M`, and `1.5 hours` display as **1 hour 30 minutes**. `120 minutes` displays as **2 hours**, and `45 minutes` stays **45 minutes**. Seconds are kept when supplied. Notes such as **includes chilling** are preserved, and uncertain text such as **overnight** or **60-90 minutes** stays as written.

The formatting applies to import previews, collection cards, recipe pages, and the editor. New saves store the formatted total time. Existing recipes display the new format without a database migration. Preparation and cooking times keep their existing formatting.

Cooking steps put each sentence on a new line, with a blank line between steps or paragraphs. The recipe page keeps the sentences of a step under one number and adds space between steps. The editor and downloaded backup use the same sentence and paragraph breaks. Decimal quantities and common abbreviations such as `tsp.` are kept intact. Existing recipes receive the display formatting without changing their stored data.

After a code change, stop the local server with `Ctrl+C` in its PowerShell window, then run `.\.venv\Scripts\python.exe -B app.py` again in that same window. Refresh the browser page to see the changes.

## What you need

- Python 3.10 or later.
- An online hosting service to access the collection from your phone and computer.
- Persistent storage on that service so recipes survive restarts and deployments.
- The Playwright Chromium browser for the automatic page-text fallback. It is installed locally under `.venv/browsers`. An online host also needs Chromium and its operating-system dependencies.

Flask handles the website requests. SQLite stores recipes in one database file. Waitress runs the website. Beautiful Soup reads recipe data from pages. Playwright runs a background Chromium browser for the second automatic import attempt. There are no AI service fees in this app.

## Paste Recipe Text

1. Select **Paste Recipe Text** on the collection page.
2. Type a complete recipe or paste one from your own notes, a website, Claude, or Codex into the same text box. You do not need to enter the title, ingredients, or steps separately.
3. Select **Format recipe**. The app separates the fields and opens the normal review screen.
4. Check the quantities, temperatures, and cooking steps, then select **Save recipe**.

The text parser handles common Markdown and plain-text recipes. It recognizes title labels or headings, servings or yield, preparation/cooking/total time labels, source links, ingredient lists, and sections named Instructions, Directions, Method, Steps, or Preparation. Timing fields can share a line, such as `Prep: 15 minutes | Cook: 20 minutes | Total: 90 minutes`. Numbered or bulleted steps are separated, and wrapped lines are joined to their step before sentence formatting. Each sentence starts on a new line, and steps are separated by a blank line. Unnumbered paragraphs separated by blank lines become separate steps.

Common chat introductions, closing offers, and sections such as Notes, Tips, Storage, and Nutrition are left out of the saved recipe. Ingredient group headings and cooking step headings are retained. A source link is optional and is taken only from an explicit source field. The app does not invent one for a chat response.

Manual typing and pasted text use the same automatic parser and review screen. There is one text-entry button. URL imports now follow this order:

1. Try the page's structured recipe data.
2. If that fails, automatically open the URL in a background browser, read the rendered page text, and pass it through the existing text formatter.
3. If that also fails, open **Paste Recipe Text** with **Manual fallback: copy the page text** instructions and an **Open the recipe page** link. Only at this stage do you need to select, copy, and paste the page text yourself.

Every successful attempt opens the review screen. Nothing is saved until you select **Save recipe**. On Windows, manual copying uses `Ctrl+A`, `Ctrl+C`, and `Ctrl+V`.

The source URL is kept in both automatic and manual attempts. At the manual stage, it is preserved separately from the text box, so replacing the whole box with copied page text does not lose it. Theme switching and a failed formatting attempt also keep the source and copy instructions. The background browser reads the page itself without changing your clipboard. It uses a fresh session and does not inherit your personal browser's logins, cookies, or open tabs. If the source blocks it or needs a subscriber session, both automatic attempts can fail and manual copying remains the last option.

The original text is available under **Original recipe text** in the review screen. It remains available if you change the theme or correct a failed save. It is not stored with the saved recipe. On the text-entry page, changing the theme also keeps the text you have entered.

The parser runs within this app and does not contact Claude or Codex. It needs no AI account connection or API key. Recipe text is limited to 200,000 characters to allow larger whole-page copies. It is intended for one recipe, rather than a full chat archive or several recipes at once. It recognizes **Steps to Make It** and plain **Step 1**, **Step 2** markers, skips common navigation and recipe controls, and stops at recognized nutrition, review, and related-recipe sections. Arbitrary prose and unusual page layouts may still need corrections in review. Missing required fields are flagged. If neither ingredients nor steps can be found, the text-entry page keeps the original text so you can try again. Formatting never saves a recipe automatically.

## Delete saved recipes

On the main page, **See all recipes** appears beside the title search. It opens every saved recipe title in one scrollable column, in title order. Each title has a checkbox. Checking one or more recipes reveals **Delete recipe(s)** and **Clear selection**. Clearing the selection hides these buttons again.

Select **Delete recipe(s)** to review a confirmation screen listing the selected titles. Nothing is deleted until you confirm. **Keep recipes** returns to the list without deleting anything. Confirming deletes only that selection and returns to the list. Theme switching keeps your selection and confirmation.

The confirmation is tied to the selected recipe IDs and the current sign-in session, and expires after ten minutes. If a selected recipe is removed before confirmation, the app stops the deletion and asks you to select again. The database write is one transaction so a failed batch does not leave a partially deleted selection.

Select **Delete recipe** on a saved recipe's card or its recipe page. The confirmation screen shows the recipe title and provides **Delete recipe** and **Keep recipe** buttons. Viewing that screen does not remove anything. Confirming removes only that recipe and returns to the saved list. Choosing **Keep recipe** returns to the recipe page.

Deletion requires sign-in and a valid form token. Both people who share the collection password can delete recipes. There is no undo button. Previously downloaded backups are not changed by a deletion.

## Local setup on Windows

The project virtual environment `.venv` is already set up. Flask 3.1.3, Beautiful Soup 4.15.0, Waitress 3.0.2, Playwright 1.65.2, and the Psycopg 3.3.9 Postgres driver are installed there. Playwright's Chromium browser is installed under `.venv/browsers`. For this copy of the app, skip the installation commands and start with the password and app secret commands below.

These commands create an isolated package folder named `.venv`. They do not publish the website. Obtain permission before running them if your workspace rules require approval for new files.

Open PowerShell in the app folder and run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location).Path '.venv\browsers'
.\.venv\Scripts\python.exe -m playwright install chromium
```

On this computer, the initial install was prevented by `PIP_NO_INDEX=1`. Installation succeeded by enabling package lookup only for that command session and selecting PyPI. No global package settings were changed. If you need to install again and see the same error, use:

```powershell
$env:PIP_NO_INDEX = '0'
.\.venv\Scripts\python.exe -m pip install --no-cache-dir --disable-pip-version-check --index-url https://pypi.org/simple -r requirements.txt
```

Create an app secret and a password hash. The password prompt hides what you type. Choose a long password, such as several unrelated words. Keep the password safe because the app cannot recover it.

```powershell
$env:APP_SECRET_KEY = (& .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))")
$env:APP_PASSWORD_HASH = (& .\.venv\Scripts\python.exe -c "import getpass; from werkzeug.security import generate_password_hash; print(generate_password_hash(getpass.getpass('Choose collection password: ')))")
$env:COOKIE_SECURE = '0'
$env:PYTHONDONTWRITEBYTECODE = '1'
.\.venv\Scripts\python.exe -B app.py
```

Open `http://127.0.0.1:8000` in your computer's browser. Sign in with the password you chose. Use `Ctrl+C` in PowerShell to stop the app. The saved recipes remain in `recipes.sqlite3`. SQLite may create a temporary journal during a database write.

These settings last only for the current PowerShell session. For later sessions, set a new secret and password hash with the commands above, or restore values from a secure password manager. Changing the secret signs out existing browser sessions. Changing the password hash changes the collection password.

The local address does not make this app available on your phone over the internet. The hosting steps below do that.

Browser setup references: https://playwright.dev/python/docs/browsers and https://playwright.dev/python/docs/network. When Playwright is upgraded, run its browser install command again so the matching browser version is available.

## Export and hosting

Start with [HOSTING.md](HOSTING.md), which now provides the Vercel setup sequence: connect Neon Postgres, configure Production secrets, update the Git repository, and deploy the Container runtime.

The updated export is `recipe-ripper-hosting.zip`. It includes `vercel.json` with `"framework": "container"` so Vercel uses the Dockerfile instead of automatically selecting the Flask runtime.

When `DATABASE_URL` or the older `POSTGRES_URL` is set, recipes use hosted Postgres. The app creates its recipe table on first connection, uses bound query values, and locks selected rows during a confirmed batch deletion. The container startup uses writable `/tmp` space for the browser and does not initialize a local data mount in this mode. On Vercel, a Postgres URL is required.

Without a Postgres URL, local use retains SQLite and the existing `recipes.sqlite3` file. Other Docker hosts can also use SQLite with a persistent volume at `/var/data`. This SQLite mount is not used on Vercel.

Set `APP_SECRET_KEY` and `APP_PASSWORD_HASH` in Vercel's private Production settings, keep `COOKIE_SECURE=1`, and connect the database with the environment-variable prefix `DATABASE` when the dialog adds `_URL`. This produces `DATABASE_URL`. Keep those credential values out of the source repository.

The package supplies `HOST=0.0.0.0`, default `PORT=8000`, and `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`. A host-supplied port overrides the default.

The ZIP excludes databases, private settings, and local environments. Update the extracted source files in `sanfordjd/recipe-ripper` on `main` after the Production settings are configured.

SQLite regression checks passed for sign-in, paste formatting, save, edit, case-insensitive search, exports, and multi-select deletion. Postgres driver options and query mappings were checked with an API test double. A live Neon database connection and Vercel's Container runtime still need verification after deployment. The saved local database was unchanged by these checks.

The browser image and compatible Linux package releases were checked. Docker is not installed on this development computer, so the Linux image has not been built locally.

## Import behavior and limits

- Reads standard Recipe JSON-LD, including objects nested in `@graph`, and standard recipe microdata as a fallback.
- If a page has several recipes, asks which one to review.
- Preserves published quantities, units, yield, and timing notes. Converts ISO duration strings to readable time labels and expresses known total times in hours and minutes.
- Does not invent missing ingredients, steps, or timing. Complete missing fields during review.
- A page that needs JavaScript, a subscriber session, or permits only browser access may fail. A gift link does not guarantee automatic import access.
- When the standard URL import fails, automatically tries rendered page text through a background browser and the existing formatter. Manual copying is offered only when this second automatic attempt also fails. The user still reviews and saves every recipe.
- The source URL is preserved, including query parameters in gift links. Anyone who has collection access can see those links.
- Imports only public HTTP(S) addresses on ordinary ports. Rejects local/private addresses and checks redirects. Connects to the IP address it checked to prevent a URL from directing a later connection to an internal service.
- Limits fetched pages to 2 MiB, limits redirect hops, and applies socket and transfer timeouts. System DNS resolution is outside the transfer timeout.
- The browser's document, scripts, and other supported resources go through the same checked public-IP transport, including redirects. Only GET requests are allowed. Images, fonts, media, additional frames, service workers, WebSockets, WebRTC, and WebTransport are blocked for this text-reading workflow. A browser attempt has a 30-second request budget, a limit of 100 intercepted requests, and a 16 MiB total resource budget. Pages that require unsupported requests may still need manual copying. Only one background import browser runs at a time.
- Recipe content is displayed as escaped plain text. Sign-in and save forms use request tokens to reject cross-site submissions.

Always review imported quantities, temperatures, and steps against the original page before saving. Ingredients use one item per line in the editor. Cooking steps use one sentence per line and a blank line between steps or paragraphs. A sentence line break does not create a new step number. Insert a blank line when you want a new step.

Example URLs supplied for validation:

- https://www.bonappetit.com/recipe/bas-best-buttermilk-biscuits
- https://cooking.nytimes.com/recipes/1013741-all-purpose-biscuits
- https://www.thespruceeats.com/quick-beer-biscuits-3051595

Live checks on November 25, 2026, using the app's importer succeeded for the Bon Appetit page and the supplied NYT gift URL. Both returned recipe titles, yield, ingredients, steps, and timing data. The Bon Appetit page did not supply a separate preparation time. The Spruce Eats page returned HTTP 403 and needs manual entry for now. Website access and content can change. Keep the supplied NYT gift URL when testing, rather than the shorter address listed above.

## Validation completed

The Python syntax check, all seven page template modes, HTML escaping, JSON-LD extraction, grouped steps, duplicate detection, microdata extraction, timing conversion, and rejection of private network addresses passed. The approved database was created and its insert, read, and rollback operations passed. No test recipes were saved.

The virtual environment is installed and its package dependency check passed. Flask loads from `.venv`, with global site packages disabled. Flask route tests passed for sign-in, session token rotation, missing and invalid form tokens, access control, save validation, saving, editing, title search, backup download, sign-out, sign-in rate limits, multiple recipe selection, import review, manual fallback, HTML escaping, response headers, and error handling. Test recipes were stored only in memory, and the saved collection was unchanged.

The app also started successfully through Waitress. Real HTTP checks passed for sign-in, session cookies, collection access, and backup download. The temporary server was then stopped. These checks did not include visual testing in a phone or computer browser.

The Bon Appetit and supplied NYT gift links were checked again using the installed environment and imported successfully. The Spruce Eats link still returned HTTP 403. No hosting account or public website has been created. No user password was stored. Before starting your own session, choose a collection password with the prompt in the setup instructions above. Hosting setup remains separate.

Checks for the UI update passed for default dark mode, saved theme preferences, theme switching on the login page, preservation of unfinished edits and multiple recipe choices, form tokens, and safe redirects. Time checks passed for hour/minute conversion, seconds, source notes, unchanged uncertain text, import previews, new saves, collection cards, recipe pages, and existing records. The saved recipe database was unchanged by these checks.

Paste-flow checks passed for whole Markdown and plain-text responses, title and metadata extraction, timing labels on one line, source links, fractions and quantities, wrapped steps, Markdown step headings, and removal of common chat text and note sections. Flask checks passed for sign-in requirements, form tokens, input limits, preservation of unrecognized input, review before saving, missing-field messages, saving and backup download, and escaped display of pasted HTML. Theme switching retained pasted text and the original response during review. Test recipes stayed in memory, and the saved collection was unchanged.

The unified text-entry checks passed for a single **Paste Recipe Text** button, automatic parsing of both typed plain text and pasted Markdown, the old manual-entry address redirecting to the same text box, and failed URL imports opening that box with the source preserved. These checks did not change the saved collection.

Sentence-spacing checks passed for punctuation, decimal quantities, common abbreviations, temperature instructions, repeated formatting, and preservation of step numbers. The paste preview, URL import, review, theme switch, save, edit, and backup paths kept the sentence and paragraph breaks. Existing recipes retained their original step groups without a database migration. Test recipes stayed in memory, and the saved collection was unchanged.

Deletion checks passed for buttons on collection cards and recipe pages, confirmation and cancellation, sign-in and form tokens, light/dark theme behavior, deletion of only the selected recipe, updated backups, and missing or already-deleted recipes. Opening the confirmation page did not delete anything. All deletion tests used an in-memory database, and existing saved recipes were unchanged.

Multi-select checks passed for the main-page link, the complete title list, title ordering, checkbox markup, the selection-dependent CSS selector, clearing selection, confirmation and cancellation, invalid IDs, duplicate selections, form tokens, signed and expired confirmations, session binding, and deletion of only the confirmed selection. Theme changes kept selections. Stale selections stopped deletion without removing the remaining recipes. A selection of 1,100 test recipes passed across database parameter batches. All tests used an in-memory database, and existing saved recipes were unchanged. The checkbox visibility was checked through its CSS selector and markup, rather than a visual browser test.

Manual whole-page fallback checks passed for preserved source links after replacing the text box, theme switching, failed formatting retries, common website headings and controls, larger pastes, and the required review/save step. Synthetic whole-page text with navigation and footer sections was used for those parsing checks. Test recipes stayed in memory, and existing saved recipes were unchanged.

The automatic fallback passed a real Chromium test using a recipe generated by JavaScript and intercepted resource responses. A full browser/HTTP test then verified that a blocked standard request triggered background extraction, preserved list items and sentence/paragraph breaks, and opened review without saving. The same browser test verified single-column collection cards and the delete button appearing/disappearing when checkboxes were selected/cleared. Test recipes stayed in memory, and temporary servers and browsers were stopped.

Route checks passed for standard import success without an unnecessary browser launch, automatic retry after missing structured data or a failed request, manual entry only after the browser attempt fails or finds incomplete recipe text, invalid URLs, and the required review/save step. Public-IP pinning, private redirect rejection, gift query preservation, and encoding headers were checked after sharing the transport with the browser. The package dependency check passed.

Live checks still succeeded for Bon Appetit and the supplied NYT gift link through the standard importer. The Spruce Eats standard request returned HTTP 403, and its automatic browser attempt did not return usable recipe text. It therefore still needs the final manual fallback in the current environment. Browser fallback success is not guaranteed for a website that restricts access.

## Open import issue

The local app previously displayed **This website restricted the import. You can enter the recipe manually.** in the user's screenshot. The screenshot did not show the source URL or exact HTTP status, so the specific cause of that attempt was not confirmed. Standard import errors now include the HTTP status where available, and trigger the automatic background-browser text attempt. Manual Select All / copy / paste is the final fallback after that second attempt fails. The Spruce Eats example still failed both automatic attempts during the latest live check.

## Backups

Use **Download a backup of all recipes** on the collection page. This downloads JSON to your browser. The app does not yet have a JSON restore button. A developer can recover recipe text from this file.

For a full database backup, stop the service before copying `recipes.sqlite3`, or use SQLite's backup tools. The database file contains the recipe collection but no login password. Keep backups private. A persistent disk is not a backup.

Email imports and a browser button are possible later additions. Neither is part of this version.
