# Put the scanner online

About 15 minutes, free, no command line. You end up with a public address like `https://YOURNAME.github.io/hk-momentum/`.

## 1. Create a GitHub account

Sign up at https://github.com/signup. Your username becomes part of the address. Skip this if you have an account.

## 2. Install GitHub Desktop

Download it from https://desktop.github.com, open it, and sign in with your GitHub account.

## 3. Upload the project

1. In GitHub Desktop choose **File > Add Local Repository**.
2. Pick the **`hk-momentum`** folder. Pick that folder only, not `claude-tv` around it: the outer folder has a `.env` file with
   your private keys.
3. It will say the folder is not a repository. Click **create a repository**, leave the suggested settings, and click
   **Create Repository**.
4. If the Changes tab lists files, type `First version` in the Summary box and click **Commit to main**.
5. Click **Publish repository**. Keep the name `hk-momentum`, **untick "Keep this code private"**, and click **Publish Repository**.
   (GitHub Pages is free only for public repositories.)

## 4. Turn on the website

1. Open `https://github.com/YOURNAME/hk-momentum` in your browser.
2. Go to **Settings > Pages**.
3. Under **Build and deployment > Source** choose **GitHub Actions**. Nothing else to fill in.

## 5. Run the first scan

1. Open the **Actions** tab. If GitHub asks, click to enable workflows. A first run may show a red cross because it started before
   step 4. Ignore it.
2. Click **Scan and publish** on the left, then **Run workflow > Run workflow**.
3. Wait about 5 minutes for a green tick.

## 6. Open your site

Go to `https://YOURNAME.github.io/hk-momentum/`, with your GitHub username in place of YOURNAME. The exact link is also on
**Settings > Pages**. Anyone with the link can use it.

From now on it updates itself on weekday evenings. GitHub can start these runs hours late, so check the date on the page.

## If something is off

| You see | Do this |
|---|---|
| 404 on the site | Check step 4 says **GitHub Actions**, then repeat step 5 and wait a couple of minutes |
| Red cross at "Save results" | **Settings > Actions > General > Workflow permissions**, choose **Read and write permissions**, save, run again |
| Red cross at "Scan" | Yahoo or HKEX was unavailable. The site keeps the last good results. Run it again later |
| Red cross at "Deploy" | Pages is not switched on yet. Do step 4 and run it again |
| A branch called `master` | Rename it to `main` under **Settings > General > Default branch** |
| Scans stopped | GitHub pauses schedules on repositories with no activity for 60 days. Click **Enable workflow** on the Actions tab |

## Changing settings later

On GitHub open `scanner/config.py`, click the pencil, edit a number, and click **Commit changes**. The site rescans and republishes in
about 5 minutes.
