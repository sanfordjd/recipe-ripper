# Host Recipe Ripper on Vercel

This version uses Vercel's Docker Container runtime and a hosted Postgres database. Local use still defaults to SQLite. The interface and recipe formatting are unchanged.

## 1. Create and connect the database

1. In your Vercel project, open **Storage** or **Marketplace**.
2. Under **Neon**, select **Create**.
3. Review the plan and price. Choose a region near your Vercel functions.
4. Leave optional **Auth** and **Realtime** features off. Recipe Ripper already handles sign-in.
5. Name the database something recognizable, such as `recipe-ripper-db`.
6. Connect the database to `recipe-ripper-hosting` for **Production**.
7. In the connection dialog, set the custom environment-variable prefix to `DATABASE` if the suffix shown is `_URL`. This produces `DATABASE_URL`. Keep **Sensitive** enabled. The app also supports the older `POSTGRES_URL` name.
8. Keep optional preview database branching off for now. Connecting to the Production environment is separate from creating a new database branch for every deployment.

The Neon integration should add `DATABASE_URL` to Vercel's private environment variables. This is the database connection value. Keep it in those settings rather than putting it in source code or a chat message.

## 2. Add the app's private settings

Open the project's **Environment Variables** settings. Make sure the following values apply to **Production**:

| Setting | Value |
| --- | --- |
| `DATABASE_URL` | Added by the connected Neon integration. The older `POSTGRES_URL` name is also supported. |
| `APP_SECRET_KEY` | A stable random secret generated below. |
| `APP_PASSWORD_HASH` | The complete password hash generated below. |
| `COOKIE_SECURE` | `1` |

Run these commands in PowerShell in the original project folder, where `.venv` is installed. They print values without saving them to files.

For `APP_SECRET_KEY`:

```powershell
.\.venv\Scripts\python.exe -B -c "import secrets; print(secrets.token_hex(32))"
```

Copy the generated value into Vercel's `APP_SECRET_KEY` field. Keep it stable across deployments.

For `APP_PASSWORD_HASH`:

```powershell
.\.venv\Scripts\python.exe -B -c "import getpass; from werkzeug.security import generate_password_hash; print(generate_password_hash(getpass.getpass('Choose hosted collection password: ')))"
```

The password prompt hides what you type. Copy the entire printed hash into Vercel's `APP_PASSWORD_HASH` field. Sign in with the password you chose. Keep that password in your password manager.

The package supplies `HOST=0.0.0.0`, a default `PORT=8000`, `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`, and `PYTHONDONTWRITEBYTECODE=1`. Vercel can supply its own port. The local `DATABASE_PATH` setting is ignored when a Postgres connection URL is present.

## 3. Update the connected GitHub repository

Extract the updated `recipe-ripper-hosting.zip` to a new folder. In `sanfordjd/recipe-ripper`, update these files from the extracted folder:

- `app.py`
- `docker-entrypoint.sh`
- `requirements.txt`
- `requirements-hosting.txt`
- `HOSTING.md`
- `README.md`

Add the new `vercel.json` at the repository's top level. It contains:

```json
{
  "framework": "container"
}
```

Keep `Dockerfile` at the top level and `templates/index.html` inside its folder. The Dockerfile, template, and ignore files are included in the ZIP, even when they have not changed.

Commit the changes to `main` after the Production database and private settings are configured. The connected Vercel project can then deploy that commit automatically. Upload the extracted source files, rather than the ZIP itself. Keep recipe databases and secrets out of the repository.

## 4. Check the deployment

The `container` framework setting tells Vercel to build the included Dockerfile, which contains the Playwright browser. It takes precedence over automatic Flask detection. Vercel documents this runtime as beta, so check its current documentation if a setting differs.

The startup script uses `/tmp` for browser scratch files when Postgres is configured. It does not try to create a local database under `/var/data` on Vercel.

In Vercel:

1. Open **Deployments** and wait for the new commit to finish.
2. Confirm the deployment uses the Container runtime and the correct Git commit.
3. If needed, use **Redeploy** after changing environment variables. New values apply to new deployments.
4. Use `/login` as the HTTP health-check path if the provider exposes that setting.
5. Open the production HTTPS address, `recipe-ripper-hosting.vercel.app`.

Your existing build and function memory settings can remain as they are while testing. Container memory has not been measured under production load.

## 5. Test the first hosted recipe

1. Sign in on your computer.
2. Use **Paste Recipe Text**, review the result, and save a test recipe.
3. Refresh and confirm it is still present.
4. Open the website on your phone and confirm you can see the same saved recipe.
5. Redeploy and confirm the test recipe remains saved. Postgres provides shared storage across function instances and deployments.
6. Test editing, title search, backup download, and confirmed deletion using sample recipes.
7. Try URL importing, including its automatic browser attempt and final manual fallback.

Both people who know the collection password can read, add, edit, and delete recipes. A first database connection creates the recipe table automatically. The ZIP contains no local recipe database, so the hosted collection starts empty unless data is separately transferred.

## If something fails

- **Setup is needed:** Check `APP_SECRET_KEY` and `APP_PASSWORD_HASH` for Production, then redeploy.
- **Saved recipe storage is not configured:** Confirm the database is connected to this project for Production and `DATABASE_URL` is present.
- **Database connection or permission error:** Review Vercel's runtime logs and the database status. The app needs a Postgres role that can create and use its recipe table.
- **Browser cannot start:** Confirm the deployment used `vercel.json` and the included Dockerfile. Vercel's automatic Flask runtime alone does not include this browser image.
- **Import runs out of memory:** Review runtime logs and available memory. Source sites can also reject both automatic attempts.
- **Sign-in does not persist:** Use HTTPS, keep `COOKIE_SECURE=1`, and keep the app secret stable.
- **Only Preview received the variables:** Connect the database and private settings to Production and redeploy.

A connection URL contains credentials. Share error descriptions or screenshots with secret values hidden.

## Local use and other container hosts

Without `DATABASE_URL` or `POSTGRES_URL`, the app continues to use the existing local SQLite database. Local PowerShell startup instructions are in README.md.

On another Docker host, either connect hosted Postgres in the same way or use SQLite with a persistent volume mounted at `/var/data`. The SQLite container setup uses `DATABASE_PATH=/var/data/recipes.sqlite3`. Vercel's temporary filesystem is not a persistent volume.

## Package and validation

The ZIP contains the app, template, Docker setup, requirements, ignore files, this guide, README.md, and `vercel.json`. It excludes passwords, local environments, browser downloads, and recipe databases.

SQLite regression checks passed for sign-in, paste formatting, saving, editing, case-insensitive search, exports, and multi-select deletion. Postgres driver options and SQL mappings were checked with an API test double, including bound values, returned IDs, and deletion row-lock queries. Those checks do not replace testing against a live Postgres database.

The local Postgres driver is installed. A live Neon connection and the hosted Container runtime still need verification after you connect the database and deploy. Docker is not installed on this development computer, so the Linux image has not been built locally.

Verified references used for this version:

- https://vercel.com/docs/functions/runtimes/container
- https://vercel.com/docs/functions/runtimes#file-system-support
- https://vercel.com/docs/storage
- https://vercel.com/docs/environment-variables
- https://neon.com/docs/guides/vercel-managed-integration
- https://www.psycopg.org/psycopg3/docs/basic/usage.html
