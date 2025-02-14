# Repository Dashboard

This repository generates an interactive dashboard that displays your GitHub organization's repository metrics using GitHub’s GraphQL API. The dashboard presents a searchable, sortable table of repository data—including open issues, open pull requests, last commit timestamp, and status (e.g., stale, archived)—along with a "Last Updated" timestamp.

## How It Works

1. **Data Generation:**  
   The `generate_table.py` script fetches repository data using a single GraphQL query. It processes each repository’s metrics and formats the data into an HTML table.

2. **Dashboard Display:**  
   The generated `index.html` file includes the dashboard with repository metrics and a "Last Updated" timestamp. The table is enhanced with [DataTables](https://datatables.net/) for easy search and sort functionality. (Note: The modal and Chart.js functionality have been removed in this version.)

3. **Automation & Deployment:**  
   A GitHub Actions workflow (see `.github/workflows/dashboard.yml`) runs the script on every commit and on a scheduled basis (once an hour). The workflow installs the required dependencies, generates the dashboard, and (optionally) deploys the output to GitHub Pages from the `gh-pages` branch.

## Setup

1. **GitHub Token:**  
   Create a GitHub personal access token (PAT) with appropriate scopes (e.g., `repo` for private repositories or sufficient public access scopes).  
   - For most cases, the default `GITHUB_TOKEN` provided by GitHub Actions is sufficient if your repository settings permit it.  
   - If you encounter permission issues (e.g., when pushing to `gh-pages`), create a PAT and add it as a secret (e.g., `PAT_TOKEN`).

2. **Add Repository Secrets:**  
   In your repository settings, navigate to **Settings > Secrets and variables > Actions** and add the following secrets:
   - `GITHUB_TOKEN` (or `PAT_TOKEN` if using a PAT)
   - `ORG_NAME` — your GitHub organization name.

3. **Workflow Configuration:**  
   The provided GitHub Actions workflow file (`.github/workflows/dashboard.yml`) is configured to:
   - Run on every push and on a schedule (once per hour).
   - Set up Python 3.10 and install the required dependencies (`requests`, `tqdm`, `loguru`).
   - Execute `generate_table.py` to produce `index.html`.
   - (Optionally) Deploy the generated dashboard to the `gh-pages` branch for GitHub Pages hosting.

4. **GitHub Pages:**  
   Enable GitHub Pages in your repository settings to deploy from the `gh-pages` branch (or use a `docs` folder if preferred). This ensures your generated `index.html` is served as your site’s entry point rather than the README.

## Dependencies

This project uses:
- [requests](https://pypi.org/project/requests/) for making HTTP requests to GitHub's GraphQL API.
- [loguru](https://pypi.org/project/loguru/) for logging.
- [DataTables](https://datatables.net/) (via CDN) for the interactive table in the dashboard.

Dependencies are installed in the GitHub Actions workflow via pip. You can also create a `requirements.txt` file if you prefer managing dependencies that way.

## Running Locally

To test the dashboard generator locally:
1. Ensure you have Python 3.10 or later installed.
2. Install dependencies with:
   ```bash
   pip install requests loguru
