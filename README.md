# Repository Dashboard

This repository generates an interactive dashboard that displays your GitHub organization's repository metrics. Active repositories are clickable—when clicked, a modal appears showing a Chart.js graph of cumulative total issues over time (bucketed by month).

## How It Works

1. **Data Generation:**  
   `generate_table.py` fetches repository data and computes time series for active repositories.

2. **Dashboard Display:**  
   The generated `index.html` includes a searchable, sortable table (via DataTables) and a modal for displaying issue trends (via Chart.js).

3. **Automation & Deployment:**  
   A GitHub Actions workflow runs the script and deploys the output to GitHub Pages.

## Setup

1. Create a GitHub personal access token.
2. Add the token as a secret named `GITHUB_TOKEN` in your repository settings.
3. Set your organization name in the workflow or via an environment variable.
4. Enable GitHub Pages to deploy from the `gh-pages` branch.
