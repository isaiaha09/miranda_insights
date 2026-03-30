# insights_website

# Isaiah's Notes for insights_website/current_website folder

This repository contains:

- `current_website/`: the Django website and Tailwind build setup
- `current_website/mobile_app/`: the Expo mobile shell that loads the Django site in a WebView
- `old_website/`: older reference files only

Most day-to-day work happens inside `current_website/`.

## Recommended local tool versions

Use these versions so everyone on the team is testing against the same baseline:

- Python: `3.12.x` recommended
- pip: latest available in the virtual environment
- Node.js: `20 LTS` recommended
- npm: `10.x` recommended
- Expo SDK: `54.0.33` (already pinned in `current_website/mobile_app/package.json`)
- React Native: `0.81.5` (already pinned)

Notes:

- The Django app dependencies are pinned in `current_website/requirements.txt`.
- The website Tailwind tooling is defined in `current_website/package.json`.
- The mobile app uses the local Expo dependency from the repo. Do not rely on an old globally installed `expo-cli`.

## First-time setup

1. Clone the repo.
2. Open the workspace root in VS Code.
3. Use PowerShell or Windows Terminal.
4. Run all Django website commands from `current_website/`.
5. Run all mobile commands from `current_website/mobile_app/`.

## Website setup

From the repository root:

```powershell
cd .\current_website
py -3.12 -m venv venv
.\venv\Scripts\Activate
python -m pip install --upgrade pip
pip install -r requirements.txt
npm install
```

If `py -3.12` is not available, install Python 3.12 first or use the matching launcher/version already installed on your machine.

## Website environment variables

Create a file named `.env` inside `current_website/`.

For local development, this is a good starter file:

```env
SECRET_KEY=replace-this-with-a-local-dev-secret
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost
CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
SITE_URL=http://127.0.0.1:8000
DJANGO_ADMIN_URL=admin

DEFAULT_FROM_EMAIL=no-reply@example.com
NEWSLETTER_FROM_EMAIL=news@example.com
CONTACT_RECIPIENT=company@mirandainsights.com
SUPPORT_EMAIL=support@mirandainsights.com
COMPANY_NOTIFICATION_EMAIL=company@mirandainsights.com

EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
EMAIL_HOST=
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=False
EMAIL_USE_SSL=False

TURNSTILE_SITE_KEY=
TURNSTILE_SECRET_KEY=
TURNSTILE_VERIFY_URL=https://challenges.cloudflare.com/turnstile/v0/siteverify
```

Local notes:

- Leaving the Turnstile keys blank disables Turnstile for local development.
- Using the console email backend prints outgoing emails in the terminal instead of sending them.
- If you need real email delivery, replace the email settings with valid SMTP credentials.

## Run the website locally

From `current_website/` with the virtual environment activated:

```powershell
python manage.py migrate
npm run build:css
python manage.py runserver
```

Open these URLs in your browser:

- Website: `http://127.0.0.1:8000/`
- Admin: `http://127.0.0.1:8000/admin/` by default, or `http://127.0.0.1:8000/<DJANGO_ADMIN_URL>/` if you changed the env var

Optional but useful:

```powershell
python manage.py createsuperuser
python manage.py check
python manage.py test
```

If you are actively editing Tailwind styles, keep this running in a second terminal from `current_website/`:

```powershell
npm run watch:css
```

## Mobile app setup

The mobile app lives in `current_website/mobile_app/` and uses Expo to load the Django site.

From the repository root:

```powershell
cd .\current_website\mobile_app
npm install
```

Create `current_website/mobile_app/.env`.

Use one of these values for `EXPO_PUBLIC_INSIGHTS_SITE_URL`:

- Physical phone on same Wi-Fi as your computer: use your computer's LAN IP, for example `http://192.168.1.172:8000`
- Android emulator: `http://10.0.2.2:8000`
- iOS simulator or local desktop testing: `http://127.0.0.1:8000`

Example:

```env
EXPO_PUBLIC_INSIGHTS_SITE_URL=http://192.168.1.172:8000
```

Important:

- Start the Django server first before opening the mobile app.
- On a physical phone, your phone and computer must be on the same network.
- Windows Firewall may prompt you to allow Python/port `8000`; allow local network access or the phone will not reach Django.

## Run the mobile app locally

1. Start the Django site from `current_website/`.
2. Open a second terminal.
3. Change into `current_website/mobile_app/`.
4. Run one of the commands below.

Recommended start command:

```powershell
npx expo start
```

Available scripts:

```powershell
npm start
npm run start:tunnel
npm run android
npm run ios
npm run web
npm run typecheck
```

Mobile testing notes:

- `npm start` and `npx expo start` use the Expo version pinned in this repo.
- Install Expo Go on your test phone to scan the QR code.
- `npm run ios` requires Apple/iOS tooling and is usually not the primary workflow on Windows.
- `npm run typecheck` is the quickest sanity check for the TypeScript mobile app.

## Folder overview

Inside `current_website/`:

- `landingpage/`: Django project settings, urls, and project-level configuration
- `apps/`: Django apps such as accounts, clients, chat, and news
- `templates/`: project-level templates
- `static/`: project-level CSS, JavaScript, and PWA assets
- `media/`: uploaded files for local development
- `manage.py`: Django management entry point
- `package.json`, `postcss.config.js`, `tailwind.config.js`: Tailwind/PostCSS tooling

## Files that should stay local-only

These should not be committed:

- `.env`
- `venv/`
- `db.sqlite3`
- `node_modules/`
- `current_website/mobile_app/.expo/`

This repo already ignores the main local-generated files in `.gitignore`.

## Quick verification checklist

Before opening a PR or handing the project to another teammate, verify these all work:

```powershell
# from current_website/
python manage.py check
python manage.py migrate
npm run build:css

# from current_website/mobile_app/
npm run typecheck
```

Then confirm:

- the Django site loads in the browser
- the admin page opens
- CSS changes compile correctly
- the mobile app connects to the local Django server

## Common issues

### Python packages fail to install

- Make sure you are using Python `3.12.x`.
- Upgrade pip inside the activated virtual environment before installing requirements.

### Tailwind changes are not showing

- Run `npm run build:css` once for a manual build.
- Use `npm run watch:css` while editing CSS.

### Phone cannot connect to Django

- Use your computer's LAN IP in `mobile_app/.env`.
- Confirm the Django server is running on port `8000`.
- Confirm Windows Firewall is not blocking the connection.
- Confirm both devices are on the same Wi-Fi network.

### Expo problems after switching Node versions

- Delete `current_website/mobile_app/node_modules/`.
- Run `npm install` again.
- Start Expo with `npx expo start`.

## Team note

If a new teammate is setting this up from scratch, the shortest successful order is:

1. Set up Python and Node.
2. Install website dependencies in `current_website/`.
3. Create `current_website/.env`.
4. Run Django migrations and start the site.
5. Install mobile dependencies in `current_website/mobile_app/`.
6. Create `current_website/mobile_app/.env` with the correct local URL.
7. Start Expo and test from Expo Go or an emulator.



    


