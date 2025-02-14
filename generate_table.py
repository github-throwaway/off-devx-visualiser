#!/usr/bin/env python3
import functools
import os
import sys
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from timeit import default_timer as timer  # For benchmarking.
from typing import Callable

import requests  # For GraphQL HTTP requests.
from loguru import logger  # Using loguru for logging
from tqdm import tqdm


# Timeit decorator to log function execution time using loguru.
def timeit(func: Callable) -> Callable:
    """Decorator to log function execution time."""

    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        start = timer()
        result = func(*args, **kwargs)
        duration = timer() - start
        logger.debug(f"'{func.__name__}' executed in {duration:.3f}s")
        return result

    return wrapped


# Define a named tuple for repository info.
RepoInfo = namedtuple("RepoInfo", ["sort_key", "row", "is_active", "repo_name", "repo_data"])


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


def fetch_repositories(org_name, token):
    """
    Fetch repository metrics for the given organization using GitHub's GraphQL API.
    Assumes fewer than 100 repositories.
    """
    query = """
    query ($orgName: String!) {
      organization(login: $orgName) {
        repositories(first: 100, orderBy: {field: PUSHED_AT, direction: DESC}) {
          nodes {
            name
            url
            pushedAt
            isArchived
            issues(states: OPEN) {
              totalCount
            }
            pullRequests(states: OPEN) {
              totalCount
            }
          }
        }
      }
    }
    """
    variables = {"orgName": org_name}
    headers = {"Authorization": f"Bearer {token}"}
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
    repos = result["data"]["organization"]["repositories"]["nodes"]
    return repos


@timeit
def main():
    """
    Main function to generate the repository dashboard HTML using GraphQL.
    """
    # For GitHub Actions, inputs are provided as environment variables prefixed with INPUT_
    token = os.environ.get("INPUT_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN") or "your_graphql_token_here"
    org_name = os.environ.get("INPUT_ORG_NAME") or os.environ.get("ORG_NAME") or "openfoodfacts"
    if not token or not org_name:
        logger.error("GITHUB_TOKEN (or INPUT_GITHUB_TOKEN) and ORG_NAME (or INPUT_ORG_NAME) must be set.")
        sys.exit(1)

    repos_data = fetch_repositories(org_name, token)
    stale_threshold = datetime.now(timezone.utc) - timedelta(days=365)

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

    with ThreadPoolExecutor(max_workers=10) as executor:
        repo_infos = list(tqdm(
            executor.map(lambda repo: process_repo(repo, stale_threshold), repos_data),
            total=len(repos_data),
            desc="Processing repositories"
        ))

    repo_infos_sorted = sorted(repo_infos, key=lambda info: info.sort_key, reverse=True)
    table_rows = "\n".join([info.row for info in repo_infos_sorted])
    html_table = header + table_rows + footer
    logger.info("Repositories sorted.")

    try:
        with open("template.html", "r", encoding="utf-8") as f:
            template = f.read()
        logger.info("Template loaded.")
    except Exception as e:
        logger.error(f"Error loading template: {e}")
        sys.exit(1)

    last_updated = datetime.now(timezone.utc).astimezone().strftime("%m/%d/%Y at %I:%M:%S %p")
    output_html = template.replace("{{TABLE_CONTENT}}", html_table)
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
