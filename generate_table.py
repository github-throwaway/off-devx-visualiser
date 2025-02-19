#!/usr/bin/env python3
import functools
import os
import sys
import urllib.parse
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from timeit import default_timer as timer
from typing import Any, Callable, Dict, List

import requests
from loguru import logger


def timeit(func: Callable) -> Callable:
    """Decorator to measure and log the execution time of a function."""

    @functools.wraps(func)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        start = timer()
        result = func(*args, **kwargs)
        duration = timer() - start
        logger.debug(f"'{func.__name__}' executed in {duration:.3f}s")
        return result

    return wrapped


@timeit
def log_and_exit(message: str) -> None:
    """Log an error message and exit the program."""
    logger.error(message)
    sys.exit(1)


@timeit
def run_graphql_query(query: str, variables: Dict[str, Any], token: str) -> Dict[str, Any]:
    """Execute a GraphQL query with provided variables and authentication token."""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": variables},
        headers=headers,
        timeout=30
    )
    if response.status_code != 200:
        log_and_exit(f"GraphQL query failed with status {response.status_code}: {response.text}")
    result = response.json()
    if "errors" in result:
        log_and_exit(f"GraphQL errors: {result['errors']}")
    return result


@timeit
def fetch_all_nodes(connection: str, owner: str, repo_name: str, token: str) -> List[Dict[str, Any]]:
    """Retrieve all open nodes for a given connection (issues or pullRequests) using pagination."""
    query = f"""
    query ($owner: String!, $name: String!, $cursor: String) {{
      repository(owner: $owner, name: $name) {{
        {connection}(states: OPEN, first: 100, after: $cursor) {{
          pageInfo {{
            hasNextPage
            endCursor
          }}
          nodes {{
            author {{
              login
            }}
          }}
        }}
      }}
    }}
    """
    all_nodes: List[Dict[str, Any]] = []
    cursor: Any = None
    while True:
        variables: Dict[str, Any] = {"owner": owner, "name": repo_name, "cursor": cursor}
        result = run_graphql_query(query, variables, token)
        connection_data = result["data"]["repository"][connection]
        all_nodes.extend(connection_data.get("nodes", []))
        if connection_data["pageInfo"]["hasNextPage"]:
            cursor = connection_data["pageInfo"]["endCursor"]
        else:
            break
    return all_nodes


@timeit
def fetch_all_issue_nodes(owner: str, repo_name: str, token: str) -> List[Dict[str, Any]]:
    """Retrieve all open issue nodes for the specified repository using pagination."""
    return fetch_all_nodes("issues", owner, repo_name, token)


@timeit
def fetch_all_pr_nodes(owner: str, repo_name: str, token: str) -> List[Dict[str, Any]]:
    """Retrieve all open pull request nodes for the specified repository using pagination."""
    return fetch_all_nodes("pullRequests", owner, repo_name, token)


RepoInfo = namedtuple("RepoInfo", ["sort_key", "row", "is_active", "repo_name", "repo_data"])


def process_repo(repo_data: Dict[str, Any], stale_threshold: datetime) -> RepoInfo:
    """Process repository data from the GraphQL API and generate an HTML table row."""
    name: str = repo_data.get("name", "Unknown")
    html_url: str = repo_data.get("url", "#")
    pushed_at_str: Any = repo_data.get("pushedAt")
    if pushed_at_str:
        last_commit = datetime.strptime(pushed_at_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        last_commit_str: str = last_commit.strftime("%Y-%m-%d %H:%M:%S")
        last_commit_order: float = last_commit.timestamp()
    else:
        last_commit = None
        last_commit_str = "N/A"
        last_commit_order = 0

    issues_total: int = repo_data.get("issues", {}).get("totalCount", 0)
    pr_total: int = repo_data.get("pullRequests", {}).get("totalCount", 0)

    statuses: List[str] = []
    stale = "<span class='stale'>Stale</span>"
    if last_commit:
        if last_commit < stale_threshold:
            statuses.append(stale)
    else:
        statuses.append(stale)
    if repo_data.get("isArchived"):
        statuses.append("Archived")
    status_str: str = ", ".join(statuses)
    is_active: bool = (stale not in status_str) and ("Archived" not in status_str)

    repo_link: str = f"<a href='{html_url}' target='_blank'>📁 {name}</a>"
    issues_link: str = f"<a href='{html_url}/issues' target='_blank'>{issues_total}</a>"
    pr_link: str = f"<a href='{html_url}/pulls' target='_blank'>{pr_total}</a>"
    commit_link: str = f"<a href='{html_url}/commits' target='_blank'>{last_commit_str}</a>"
    active_class: str = " class='active-row'" if is_active else ""

    row: str = (
        f"<tr{active_class} data-repo='{name}'>"
        f"<td>{repo_link}</td>"
        f"<td data-order='{issues_total}'>{issues_link}</td>"
        f"<td data-order='{pr_total}'>{pr_link}</td>"
        f"<td data-order='{last_commit_order}'>{commit_link}</td>"
        f"<td>{status_str}</td>"
        f"</tr>"
    )
    sort_key: datetime = last_commit if last_commit else datetime(1970, 1, 1, tzinfo=timezone.utc)
    return RepoInfo(sort_key, row, is_active, name, repo_data)


@timeit
def fetch_repositories(org_name: str, token: str) -> List[Dict[str, Any]]:
    """
    Fetch repository metrics for the given organization using GitHub's GraphQL API.
    Now includes labels (first 100) for each repository.
    """
    query = """
    query ($orgName: String!, $cursor: String) {
      organization(login: $orgName) {
        repositories(first: 5, after: $cursor, orderBy: {field: PUSHED_AT, direction: DESC}) {
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
            labels(first: 100) {
              totalCount
              pageInfo {
                hasNextPage
                endCursor
              }
              nodes {
                name
                color
                description
                issues(states: OPEN) {
                  totalCount
                }
              }
            }
          }
        }
      }
    }
    """
    repos: List[Dict[str, Any]] = []
    cursor: Any = None
    while True:
        variables: Dict[str, Any] = {"orgName": org_name, "cursor": cursor}
        result = run_graphql_query(query, variables, token)
        data: Dict[str, Any] = result.get("data", {}).get("organization", {}).get("repositories", {})
        repos.extend(data.get("nodes", []))
        if data.get("pageInfo", {}).get("hasNextPage"):
            cursor = data["pageInfo"]["endCursor"]
        else:
            break
    return repos


@timeit
def fetch_all_labels(owner: str, repo_name: str, token: str) -> List[Dict[str, Any]]:
    """
    Fetch all labels for a given repository using pagination.
    Each label includes its name, color, description, and the total count of open issues.
    """
    query = """
    query ($owner: String!, $name: String!, $cursor: String) {
      repository(owner: $owner, name: $name) {
        labels(first: 100, after: $cursor) {
          pageInfo {
            hasNextPage
            endCursor
          }
          nodes {
            name
            color
            description
            issues(states: OPEN) {
              totalCount
            }
          }
        }
      }
    }
    """
    all_labels = []
    cursor = None
    while True:
        variables = {"owner": owner, "name": repo_name, "cursor": cursor}
        result = run_graphql_query(query, variables, token)
        labels_data = result["data"]["repository"]["labels"]
        all_labels.extend(labels_data.get("nodes", []))
        if labels_data["pageInfo"]["hasNextPage"]:
            cursor = labels_data["pageInfo"]["endCursor"]
        else:
            break
    return all_labels


def get_text_color_for_bg(hex_color: str) -> str:
    """
    Return either '#000000' or '#ffffff' for maximum contrast
    depending on the brightness of the given hex color (without '#').
    """
    hex_color = hex_color.strip().lstrip('#')
    # Fallback if the color is malformed
    if len(hex_color) != 6:
        return '#ffffff'
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    # Simple relative luminance calculation
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return '#000000' if luminance > 128 else '#ffffff'


@timeit
def generate_labels_section_grouped_by_repo(repos_data: List[Dict[str, Any]], org_name: str) -> str:
    """
    Generate an HTML section grouping labels by repository.
    - Removes extra "Labels" subhead.
    - Groups labels by their open issue count; each group is a table row.
    - Uses a 2-column layout: first column for label badges, second for issue count.
    - Dynamically adjusts label text color for better contrast.
    - Highlights issue count if zero, with consistent borders and spacing.
    """
    sections = []
    for repo in repos_data:
        repo_name = repo.get("name", "Unknown")
        repo_url = repo.get("url", "#")

        # Get all labels (already fetched in your code)
        labels = repo.get("labels", {}).get("nodes", [])
        if not labels:
            continue

        # Group labels by their open issues count
        groups: Dict[int, List[Dict[str, Any]]] = {}
        for label in labels:
            count = label.get("issues", {}).get("totalCount", 0)
            groups.setdefault(count, []).append(label)

        # Sort groups by issue count ascending
        sorted_counts = sorted(groups.keys())

        # Start building the HTML for this repository’s label section
        section_html = (
            f"<div class='repo-labels'>\n"
            f"  <h3><a href='{repo_url}' target='_blank'>{repo_name}</a></h3>\n"
            # 2-column table with consistent borders and spacing
            f"  <table class='labels-table' style='width:100%; border-collapse:collapse; table-layout:fixed;'>\n"
            f"    <thead>\n"
            f"      <tr>\n"
            f"        <th style='width:80%;'>Labels</th>\n"
            f"        <th style='width:20%;'>Open Issues</th>\n"
            f"      </tr>\n"
            f"    </thead>\n"
            f"    <tbody>\n"
        )

        row_index = 0
        for count in sorted_counts:
            label_group = groups[count]
            # Sort labels alphabetically by name within the group
            label_group.sort(key=lambda x: x.get("name", "").lower())

            # Build badge HTML for each label in the group
            badges = []
            for label in label_group:
                label_name = label.get("name", "")
                color_hex = label.get("color", "000000")
                text_color = get_text_color_for_bg(color_hex)
                label_query = urllib.parse.quote(f'is:open label:"{label_name}"')
                label_url = f"{repo_url}/issues?q={label_query}"
                badge_html = (
                    f"<a href='{label_url}' target='_blank'>"
                    f"  <span class='gh-label' "
                    f"        style='background-color: #{color_hex}; color: {text_color};'>"
                    f"{label_name}</span>"
                    f"</a>"
                )
                badges.append(badge_html)

            # Join all label badges in this group
            badges_html = " ".join(badges)

            # Determine row style for alternating backgrounds
            row_class = "even" if row_index % 2 == 0 else "odd"

            # Highlight the count cell if the count is zero
            count_class = "count no-issues" if count == 0 else "count"
            section_html += (
                f"      <tr class='{row_class}' "
                f"          style='border-bottom:1px solid #ccc;'>\n"
                f"        <td style='padding:8px; border-right:1px solid #ccc;'>{badges_html}</td>\n"
                f"        <td style='padding:8px;' class='{count_class}'>{count}</td>\n"
                f"      </tr>\n"
            )
            row_index += 1

        section_html += (
            "    </tbody>\n"
            "  </table>\n"
            "</div>\n"
        )
        sections.append(section_html)

    return "\n".join(sections)

@timeit
def generate_contrib_table(contrib_data: Dict[str, Dict[str, int]], org_name: str) -> str:
    """
    Generate an HTML table for contributors sorted by the number of open issues and pull requests.
    """
    header: str = (
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
    rows: List[str] = []
    sorted_contribs = sorted(
        contrib_data.items(), key=lambda x: (x[1]["issues"], x[1]["prs"]), reverse=True
    )
    for login, counts in sorted_contribs:
        issues_link: str = (
            f"<a href='https://github.com/search?q=type:issue+author:{login}+is:open+org:{org_name}' "
            f"target='_blank'>{counts['issues']}</a>"
        )
        prs_link: str = (
            f"<a href='https://github.com/search?q=type:pr+author:{login}+is:open+org:{org_name}' "
            f"target='_blank'>{counts['prs']}</a>"
        )
        author_link: str = f"<a href='https://github.com/{login}' target='_blank'>👤 {login}</a>"
        row: str = (
            f"<tr>"
            f"<td>{author_link}</td>"
            f"<td data-order='{counts['issues']}'>{issues_link}</td>"
            f"<td data-order='{counts['prs']}'>{prs_link}</td>"
            f"</tr>"
        )
        rows.append(row)
    footer: str = "</tbody></table>"
    return header + "\n".join(rows) + footer


@timeit
def aggregate_contributor_data(repos_data: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """
    Aggregate open issues and pull requests counts per contributor across repositories.
    """
    contrib_data: Dict[str, Dict[str, int]] = {}
    for repo in repos_data:
        for issue in repo.get("issues", {}).get("nodes", []):
            author: Any = issue.get("author")
            if author and "login" in author:
                login: str = author["login"]
                contrib_data.setdefault(login, {"issues": 0, "prs": 0})
                contrib_data[login]["issues"] += 1
        for pr in repo.get("pullRequests", {}).get("nodes", []):
            author = pr.get("author")
            if author and "login" in author:
                login = author["login"]
                contrib_data.setdefault(login, {"issues": 0, "prs": 0})
                contrib_data[login]["prs"] += 1
    return contrib_data


@timeit
def load_template(filepath: str) -> str:
    """
    Load and return the contents of the HTML template file.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            template: str = f.read()
        logger.info("Template loaded.")
        return template
    except Exception as e:
        log_and_exit(f"Error loading template: {e}")


@timeit
def write_output_file(filepath: str, content: str) -> None:
    """
    Write the provided content to a file.
    """
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"{filepath} generated successfully.")
    except Exception as e:
        log_and_exit(f"Error writing {filepath}: {e}")


@timeit
def fetch_remaining_labels(owner: str, repo_name: str, token: str, start_cursor: str) -> List[Dict[str, Any]]:
    """
    Fetch remaining labels for a repository starting from the given cursor.
    """
    query = """
    query ($owner: String!, $name: String!, $cursor: String) {
      repository(owner: $owner, name: $name) {
        labels(first: 100, after: $cursor) {
          pageInfo {
            hasNextPage
            endCursor
          }
          nodes {
            name
            color
            description
            issues(states: OPEN) {
              totalCount
            }
          }
        }
      }
    }
    """
    all_labels = []
    cursor = start_cursor
    while True:
        variables = {"owner": owner, "name": repo_name, "cursor": cursor}
        result = run_graphql_query(query, variables, token)
        labels_data = result["data"]["repository"]["labels"]
        all_labels.extend(labels_data.get("nodes", []))
        if labels_data["pageInfo"]["hasNextPage"]:
            cursor = labels_data["pageInfo"]["endCursor"]
        else:
            break
    return all_labels


@timeit
def main() -> None:
    logger.info("Started execution.")
    """
    Main function to generate the repository dashboard HTML using GitHub's GraphQL API.
    Includes generation of the labels section grouped by repository in the third tab.
    """
    token: str = (
            os.environ.get("INPUT_GITHUB_TOKEN")
            or os.environ.get("GITHUB_TOKEN")
            or "your_graphql_token_here"
    )
    org_name: str = os.environ.get("INPUT_ORG_NAME") or os.environ.get("ORG_NAME") or "openfoodfacts"
    if not token or not org_name:
        log_and_exit("GITHUB_TOKEN (or INPUT_GITHUB_TOKEN) and ORG_NAME (or INPUT_ORG_NAME) must be set.")

    logger.info("Fetching repositories ...")
    repos_data: List[Dict[str, Any]] = fetch_repositories(org_name, token)

    for repo in repos_data:
        owner = org_name  # Assuming the owner is the organization.
        # (Existing issue and PR pagination logic here …)

        # Merge additional labels if totalCount > fetched labels count.
        labels_data = repo.get("labels", {})
        total_labels = labels_data.get("totalCount", 0)
        fetched_labels = labels_data.get("nodes", [])
        if total_labels > len(fetched_labels):
            additional = fetch_remaining_labels(owner, repo["name"], token, labels_data["pageInfo"]["endCursor"])
            repo["labels"]["nodes"].extend(additional)
            logger.debug(f"Fetched additional {len(additional)} labels for repository {repo['name']}.")

    stale_threshold: datetime = datetime.now(timezone.utc) - timedelta(days=365)

    repo_table_header: str = (
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
    repo_table_footer: str = "</tbody></table>"

    repo_infos = [process_repo(repo, stale_threshold) for repo in repos_data]
    repo_infos_sorted = sorted(repo_infos, key=lambda info: info.sort_key, reverse=True)
    table_rows: str = "\n".join(info.row for info in repo_infos_sorted)
    html_repo_table: str = repo_table_header + table_rows + repo_table_footer
    logger.info("Repositories table generated.")

    logger.info("Fetching contributors ...")

    contrib_data: Dict[str, Dict[str, int]] = aggregate_contributor_data(repos_data)
    html_contrib_table: str = generate_contrib_table(contrib_data, org_name)

    # Generate labels section grouped by repository.
    logger.info("Fetching labels ...")
    html_labels_section = generate_labels_section_grouped_by_repo(repos_data, org_name)

    template: str = load_template("template.html")
    last_updated: str = datetime.now(timezone.utc).astimezone().strftime("%m/%d/%Y at %I:%M:%S %p")
    output_html: str = template.replace("{{REPO_TABLE}}", html_repo_table)
    output_html = output_html.replace("{{CONTRIB_TABLE}}", html_contrib_table)
    output_html = output_html.replace("{{LABELS_TABLE}}", html_labels_section)
    output_html = output_html.replace("{{LAST_UPDATED}}", last_updated)

    write_output_file("index.html", output_html)


if __name__ == "__main__":
    main()
