#!/usr/bin/env python3
import functools
import os
import sys
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from timeit import default_timer as timer  # For benchmarking.
from typing import Callable

import requests  # For GraphQL HTTP requests.
from loguru import logger  # For improved logging.

# -----------------------------
# Timeit decorator for performance logging.
# -----------------------------
def timeit(func: Callable) -> Callable:
    """Decorator to log function execution time using loguru."""
    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        start = timer()
        result = func(*args, **kwargs)
        duration = timer() - start
        logger.debug(f"'{func.__name__}' executed in {duration:.3f}s")
        return result
    return wrapped

# -----------------------------
# Define a named tuple for repository information.
# -----------------------------
RepoInfo = namedtuple("RepoInfo", ["sort_key", "row", "is_active", "repo_name", "repo_data"])

# -----------------------------
# Process a repository's data into an HTML table row.
# -----------------------------
def process_repo(repo_data, stale_threshold):
    """
    Process a repository dictionary from the GraphQL API and generate an HTML table row.
    """
    name = repo_data['name']
    html_url = repo_data['url']

    pushed_at_str = repo_data.get('pushedAt')
    if pushed_at_str:
        last_commit = datetime.strptime(pushed_at_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        last_commit_str = last_commit.strftime("%Y-%m-%d %H:%M:%S")
    else:
        last_commit = None
        last_commit_str = "N/A"

    issues_total = repo_data['issues']['totalCount']
    pr_total = repo_data['pullRequests']['totalCount']
    open_issues = issues_total
    open_pr_count = pr_total

    statuses = []
    if last_commit:
        if last_commit < stale_threshold:
            statuses.append("<span class='stale'>Stale</span>")
    else:
        statuses.append("<span class='stale'>Stale</span>")
    if repo_data.get('isArchived'):
        statuses.append("Archived")
    status_str = ", ".join(statuses)

    is_active = ("<span class='stale'>Stale</span>" not in status_str) and ("Archived" not in status_str)

    repo_link = f"<a href='{html_url}' target='_blank'>📁 {name}</a>"
    issues_link = f"<a href='{html_url}/issues' target='_blank'>{open_issues}</a>"
    pr_link = f"<a href='{html_url}/pulls' target='_blank'>🔀 {open_pr_count}</a>"
    commit_link = f"<a href='{html_url}/commits' target='_blank'>{last_commit_str}</a>"

    active_class = " class='active-row'" if is_active else ""
    row = (
        f"<tr{active_class} data-repo='{name}'>"
        f"<td>{repo_link}</td>"
        f"<td>{issues_link}</td>"
        f"<td>{pr_link}</td>"
        f"<td>{commit_link}</td>"
        f"<td>{status_str}</td>"
        f"</tr>"
    )

    sort_key = last_commit if last_commit else datetime(1970, 1, 1, tzinfo=timezone.utc)
    return RepoInfo(sort_key, row, is_active, name, repo_data)

# -----------------------------
# Fetch repositories using GitHub's GraphQL API with pagination.
# -----------------------------
def fetch_repositories(org_name, token):
    """
    Fetch repository metrics for the given organization using GitHub's GraphQL API.
    Now supports pagination to retrieve all repositories.
    """
    query = """
    query ($orgName: String!, $cursor: String) {
      organization(login: $orgName) {
        repositories(first: 50, after: $cursor, orderBy: {field: PUSHED_AT, direction: DESC}) {
          pageInfo {
            hasNextPage
            endCursor
          }
          nodes {
            name
            url
            pushedAt
            isArchived
            issues(states: OPEN, first: 100) {
              totalCount
              nodes {
                author {
                  login
                }
              }
            }
            pullRequests(states: OPEN, first: 100) {
              totalCount
              nodes {
                author {
                  login
                }
              }
            }
          }
        }
      }
    }
    """
    headers = {"Authorization": f"Bearer {token}"}
    repos = []
    cursor = None
    while True:
        variables = {"orgName": org_name, "cursor": cursor}
        response = requests.post("https://api.github.com/graphql",
                                 json={"query": query, "variables": variables},
                                 headers=headers)
        if response.status_code != 200:
            logger.error(f"GraphQL query failed with status {response.status_code}: {response.text}")
            sys.exit(1)
        result = response.json()
        if "errors" in result:
            logger.error(f"GraphQL errors: {result['errors']}")
            sys.exit(1)
        data = result["data"]["organization"]["repositories"]
        repos.extend(data["nodes"])
        if data["pageInfo"]["hasNextPage"]:
            cursor = data["pageInfo"]["endCursor"]
        else:
            break
    return repos

# -----------------------------
# Generate contributor table HTML from aggregated data.
# -----------------------------
def generate_contrib_table(contrib_data):
    """
    Generate an HTML table for contributors sorted by the number of open issues.
    """
    header = (
        "<table id='contribTable' class='display' style='width:100%'>"
        "<thead>"
        "<tr>"
        "<th>Contributor</th>"
        "<th>Open Issues</th>"
        "<th>Open PRs</th>"
        "</tr>"
        "</thead>"
        "<tbody>"
    )
    rows = ""
    # Sort contributors by open issues (and then by PRs) in descending order.
    sorted_contribs = sorted(contrib_data.items(), key=lambda x: (x[1]["issues"], x[1]["prs"]), reverse=True)
    for login, counts in sorted_contribs:
        issues_link = f"<a href='https://github.com/search?q=type:issue+author:{login}+is:open' target='_blank'>{counts['issues']}</a>"
        prs_link = f"<a href='https://github.com/search?q=type:pr+author:{login}+is:open' target='_blank'>{counts['prs']}</a>"
        row = f"<tr><td>{login}</td><td>{issues_link}</td><td>{prs_link}</td></tr>"
        rows += row + "\n"
    footer = "</tbody></table>"
    return header + rows + footer

# -----------------------------
# Main function to generate the dashboard.
# -----------------------------
@timeit
def main():
    """
    Main function to generate the repository dashboard HTML using GraphQL.
    Designed to work as a GitHub Action.
    """
    # For GitHub Actions, inputs are provided as environment variables prefixed with INPUT_.
    token = os.environ.get("INPUT_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN") or "your_graphql_token_here"
    org_name = os.environ.get("INPUT_ORG_NAME") or os.environ.get("ORG_NAME") or "openfoodfacts"
    if not token or not org_name:
        logger.error("GITHUB_TOKEN (or INPUT_GITHUB_TOKEN) and ORG_NAME (or INPUT_ORG_NAME) must be set.")
        sys.exit(1)

    repos_data = fetch_repositories(org_name, token)
    stale_threshold = datetime.now(timezone.utc) - timedelta(days=365)

    # Build repository table.
    header = (
        "<table id='repoTable' class='display' style='width:100%'>"
        "<thead>"
        "<tr>"
        "<th>Repository</th>"
        "<th>Open Issues</th>"
        "<th>Open PRs</th>"
        "<th>Last Commit</th>"
        "<th>Status</th>"
        "</tr>"
        "</thead>"
        "<tbody>"
    )
    footer = "</tbody></table>"

    repo_infos = [process_repo(repo, stale_threshold) for repo in repos_data]
    repo_infos_sorted = sorted(repo_infos, key=lambda info: info.sort_key, reverse=True)
    table_rows = "\n".join([info.row for info in repo_infos_sorted])
    html_table = header + table_rows + footer
    logger.info("Repositories sorted.")

    # Aggregate contributor data.
    contrib_data = {}
    for repo in repos_data:
        # Aggregate open issues.
        for issue in repo['issues'].get('nodes', []):
            if issue and issue.get('author') and issue['author'] and 'login' in issue['author']:
                login = issue['author']['login']
                contrib_data.setdefault(login, {"issues": 0, "prs": 0})
                contrib_data[login]["issues"] += 1
        # Aggregate open pull requests.
        for pr in repo['pullRequests'].get('nodes', []):
            if pr and pr.get('author') and pr['author'] and 'login' in pr['author']:
                login = pr['author']['login']
                contrib_data.setdefault(login, {"issues": 0, "prs": 0})
                contrib_data[login]["prs"] += 1

    contrib_table = generate_contrib_table(contrib_data)

    try:
        with open("template.html", "r", encoding="utf-8") as f:
            template = f.read()
        logger.info("Template loaded.")
    except Exception as e:
        logger.error(f"Error loading template: {e}")
        sys.exit(1)

    last_updated = datetime.now(timezone.utc).astimezone().strftime("%m/%d/%Y at %I:%M:%S %p")
    output_html = template.replace("{{REPO_TABLE}}", html_table)
    output_html = output_html.replace("{{CONTRIB_TABLE}}", contrib_table)
    output_html = output_html.replace("{{LAST_UPDATED}}", last_updated)

    try:
        with open("index.html", "w", encoding="utf-8") as f:
            f.write(output_html)
        logger.info("index.html generated successfully.")
    except Exception as e:
        logger.error(f"Error writing index.html: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
