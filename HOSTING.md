# Host Recipe Ripper

Start here when choosing a host. This app needs a running Python service, a browser for automatic recipe imports, and storage for your saved recipes. The hosting package includes setup files for all three. You do not need to install Docker on your computer just to give this package to a host.

## What to search for

Use search terms such as:

- `Docker web app hosting persistent disk`
- `Python Flask hosting SQLite persistent storage`
- `Playwright Chromium container hosting`

Choose a web application hosting service that can build a Dockerfile or run a Docker container. Here are the requirements to check:

| Requirement | What it means for this app |
| --- | --- |
| Dockerfile builds | The host builds the included `Dockerfile` and runs the app with its Chromium browser. |
| Persistent disk or volume | Mount it at `/var/data`. Saved recipes must survive service restarts and deployments. |
| HTTPS | The provider should supply a secure web address and certificate. This is needed for sign-in cookies. |
| Private environment variables | You enter the app secret and password hash in the host's private settings. |
| Outbound internet access | The app needs HTTPS access to recipe sites and their page resources. |
| Memory that can be increased | Compare plans around 2 GB RAM as a suggested starting point for the browser. Peak container memory has not been measured, so confirm this with the provider. |
| One running instance | This version uses one SQLite database and should run as a single instance. |
| Long enough request timeout | Automatic importing can take approximately a minute when both attempts run. Confirm the host will allow it. |
| Storage backups | Check the provider's disk backup options. Also use the app's recipe download feature. |

You can send a provider this question:

> Can you build and host a Docker web app that runs Python and Playwright Chromium, uses one instance, has a persistent volume mounted at /var/data, supports private environment variables, and provides HTTPS? Can it make outbound web requests and allow imports that may take approximately a minute? The app starts with a volume initialization step, then runs as user ID 10001. Will that work on your service?

The startup script needs permission to initialize the mounted directory before it drops to the ordinary app user. If a provider forces a different user or volume path, the package will need an adjustment for that provider.

Render is one example of a provider with Docker services and persistent disks. Its documentation says persistent disks require a paid service. Other providers may offer different plans. Check the total price, memory, storage, and backup costs before choosing. No host has been chosen or purchased for this package.

## What is in the ZIP

Extract `recipe-ripper-hosting.zip` to a new folder. It contains:

- `app.py` and `templates/index.html`, the app and interface.
- `Dockerfile` and `docker-entrypoint.sh`, the installation and startup instructions used by a container host.
- `requirements-hosting.txt`, the exact Python package versions for hosting.
- `requirements.txt`, the package ranges used for local setup.
- `.dockerignore` and `.gitignore`, which keep local data and secrets out of builds and source uploads.
- `HOSTING.md` and `README.md`, the hosting and app guides.

The ZIP excludes your local virtual environment, downloaded Windows browser, recipe database, and passwords. The host obtains the correct Linux browser from the container image. A first hosted launch creates an empty collection. Your local database stays on this computer. If you later need to move local recipes, transfer them privately as a separate step.

## The basic hosting sequence

1. Extract the ZIP. Check that `Dockerfile` is beside `app.py` in the extracted folder.
2. Choose a host that meets the requirements above.
3. If the host asks for a source repository, create a private GitHub repository and upload the extracted files with `Dockerfile` at the top level. Some hosts accept a source upload instead.
4. Create a Docker web service from that source. Use the included Dockerfile and default startup command. You should not need a separate Python build or browser install command.
5. Add a persistent disk mounted at `/var/data` before using the app. Choose a size appropriate for your recipes and confirm the price.
6. Set the two required private values described below: `APP_SECRET_KEY` and `APP_PASSWORD_HASH`.
7. Set the HTTP health-check path to `/login` if the provider offers that setting. Keep one running instance. Configure the provider's request timeout to accommodate automatic imports.
8. Deploy the service. The provider builds the package, then gives you an HTTPS web address.
9. Open that address, sign in, and try the checks below. Then open the same address on your phone.

You can use the host's supplied address. You do not need to buy a domain name to start.

## Generate the private settings

Run these commands in PowerShell in the original project folder, where `.venv` is already installed. These commands do not save secrets to files or change the local app's settings. The output is for the host's private settings.

For `APP_SECRET_KEY`:

```powershell
.\.venv\Scripts\python.exe -B -c "import secrets; print(secrets.token_hex(32))"
```

Copy the generated value into the host's `APP_SECRET_KEY` field. Keep it stable across deployments so existing sign-in sessions remain valid.

For `APP_PASSWORD_HASH`:

```powershell
.\.venv\Scripts\python.exe -B -c "import getpass; from werkzeug.security import generate_password_hash; print(generate_password_hash(getpass.getpass('Choose hosted collection password: ')))"
```

The password prompt hides what you type. Copy the entire printed hash into the host's `APP_PASSWORD_HASH` field. Sign in to the website with the password you chose, rather than with that hash. Keep the password in your password manager. The app has no password-reset email feature.

Enter these values only in the host's private environment settings. They do not belong in your GitHub repository, Dockerfile, ZIP, or chat messages. If your host can generate a random secret for you, it can generate `APP_SECRET_KEY` instead of the first command.

The package supplies these defaults:

| Setting | Default |
| --- | --- |
| `HOST` | `0.0.0.0` |
| `PORT` | `8000`, or the value supplied by your host |
| `DATABASE_PATH` | `/var/data/recipes.sqlite3` |
| `COOKIE_SECURE` | `1` |
| `PLAYWRIGHT_BROWSERS_PATH` | `/ms-playwright` |
| `PYTHONDONTWRITEBYTECODE` | `1` |

Keep these defaults for the included Docker package. In particular, do not copy `COOKIE_SECURE=0` from local testing to HTTPS hosting. The startup script uses the fixed database path above to initialize the persistent disk.

`TRUSTED_HOSTS` is optional for the first launch. After the provider gives you a hostname, you can restrict it to that hostname, without `https://`. Confirm the provider's health checks still work after that change.

## Check the first deployment

Before relying on the hosted collection:

1. Sign in on your computer and phone.
2. Paste a recipe response, review it, and save it.
3. Refresh the page and confirm the recipe is still there.
4. Restart or redeploy the hosted service and confirm the recipe remains saved. This checks that the database is on the persistent disk.
5. Try a URL import. Check the automatic text attempt and final manual fallback when needed. Source sites can still reject both automatic attempts.
6. Download a recipe backup. Test deleting a sample recipe and confirming a multiple-recipe deletion.

Both people who know the collection password can read, add, edit, and delete recipes. Keep the password private.

## If deployment fails

- **Missing secret or password hash:** Set both private values, then restart the service.
- **Cannot write the database:** Confirm the persistent volume is mounted at `/var/data` and the startup script can initialize its ownership.
- **Recipes disappear after restart:** Confirm `DATABASE_PATH` and the persistent mount. A temporary filesystem is not saved storage.
- **Automatic browser cannot start:** Check that the service used the Dockerfile and the pinned hosting requirements. Increase memory if the host reports an out-of-memory failure.
- **Sign-in does not persist:** Use the HTTPS address and keep `COOKIE_SECURE=1`. Keep the app secret stable.
- **Imports stop before completion:** Check the provider's HTTP request timeout and outbound network access.

## What has been verified

The local app's behavior, automatic browser fallback, and authentication were tested before packaging. The pinned Playwright container image was found in its official registry, and the pinned package releases have compatible Linux downloads. The export ZIP was checked for its exact file list and matching source contents.

Docker is not installed on the development computer, so the Linux image has not been built or run locally. The first deployment must still verify the container build, host permissions, persistent storage, and available memory. This is an export package, not an already published website.

Provider screens, prices, and plans can change. Check the provider's current documentation when you sign up. Verified references used to prepare this package:

- https://playwright.dev/python/docs/docker
- https://render.com/docs/docker
- https://render.com/docs/disks
- https://render.com/docs/health-checks
