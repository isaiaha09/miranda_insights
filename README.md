# insights_website

Isaiah's Edits:

### NOTE: These notes will be about insights_website/current_website with the exception of this README.md ###

    Necessities (to run on your local machine/server):
    - requirements.txt (all dependencies listed in this textfile. Type "pip install -r requirements.txt" in insights_website/current_website cd in terminal)
    - .env (add .env file normally in vs code add file icon)
    - venv (type "python -m venv venv" in insights_website/current_website cd in terminal)
    - node_modules for tailwind.css (type "npm install" in insights_website/current_website cd in terminal)

    Folders:
    - landingpage (project folder)
    - apps (startapps folder)
    - templates (project level templates)
    - static (project level css/js files)

    Other Files under insights_website/current_website folder:
    - .gitignore 
    - manage.py
    - package.json, postcss.config.js, and tailwind.config.js (all for tailwind.css)

    *** .gitignore ***
    Make sure the following are in .gitignore:
    - node_modules (unnecessary for git repo)
    - .env (hides all of our secret keys and api keys)
    - db.sqlite3 and other sqlite dbs (stores data from local machine. Cannot have that in github repo)
    - venv (also unnecessary for git repo. venv should be created and activated in own local machine)




    EMAILS:
        company@mirandainsights.com (emails/messages get received)
        news@mirandainsights.com (news letter aesthetic email)
        suppor@mirandainsights.com (visual email when sending messages to and from company@mirandainsights email from clients pov)

    
    Security:
        - Implement cloudflare turnstiles in contact form and registration



    


