#!/usr/bin/env python3
import functools
import os
import sys
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from timeit import default_timer as timer
from typing import Any, Callable, Dict, List

import requests
from loguru import logger


def timeit(func: Callable) -> Callable:
    """
    Decorator to measure and log the execution time of a function.

    Args:
        func: The function to be decorated.

    Returns:
        The wrapped function with timing measurement.
    """

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
    """
    Log an error message and exit the program.

    Args:
        message: The error message to log.
    """
    logger.error(message)
    sys.exit(1)


@timeit
def run_graphql_query(query: str, variables: Dict[str, Any], token: str) -> Dict[str, Any]:
    """
    Execute a GraphQL query with provided variables and authentication token.

    Args:
        query: The GraphQL query string.
        variables: A dictionary of query variables.
        token: The GitHub authentication token.

    Returns:
        The JSON response from the GraphQL API as a dictionary.
    """
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": variables},
        headers=headers
    )
    if response.status_code != 200:
        log_and_exit(f"GraphQL query failed with status {response.status_code}: {response.text}")
    result = response.json()
    if "errors" in result:
        log_and_exit(f"GraphQL errors: {result['errors']}")
    return result


@timeit
def fetch_all_nodes(connection: str, owner: str, repo_name: str, token: str) -> List[Dict[str, Any]]:
    """
    Retrieve all open nodes for a given connection (issues or pullRequests) using pagination.

    Args:
        connection: The connection type ('issues' or 'pullRequests').
        owner: The repository owner.
        repo_name: The repository name.
        token: The GitHub authentication token.

    Returns:
        A list of node dictionaries retrieved from the GraphQL API.
    """
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
    """
    Retrieve all open issue nodes for the specified repository using pagination.

    Args:
        owner: The repository owner.
        repo_name: The repository name.
        token: The GitHub authentication token.

    Returns:
        A list of issue node dictionaries.
    """
    return fetch_all_nodes("issues", owner, repo_name, token)


@timeit
def fetch_all_pr_nodes(owner: str, repo_name: str, token: str) -> List[Dict[str, Any]]:
    """
    Retrieve all open pull request nodes for the specified repository using pagination.

    Args:
        owner: The repository owner.
        repo_name: The repository name.
        token: The GitHub authentication token.

    Returns:
        A list of pull request node dictionaries.
    """
    return fetch_all_nodes("pullRequests", owner, repo_name, token)


RepoInfo = namedtuple("RepoInfo", ["sort_key", "row", "is_active", "repo_name", "repo_data"])


def process_repo(repo_data: Dict[str, Any], stale_threshold: datetime) -> RepoInfo:
    """
    Process repository data from the GraphQL API and generate an HTML table row.

    Args:
        repo_data: A dictionary containing repository data.
        stale_threshold: A datetime threshold for marking a repository as stale.

    Returns:
        A RepoInfo named tuple containing the sort key, HTML row, activity status,
        repository name, and original repository data.
    """
    name: str = repo_data.get("name", "Unknown")
    html_url: str = repo_data.get("url", "#")
    pushed_at_str: Any = repo_data.get("pushedAt")
    if pushed_at_str:
        last_commit = datetime.strptime(pushed_at_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        last_commit_str: str = last_commit.strftime("%Y-%m-%d %H:%M:%S")
        last_commit_order: float = last_commit.timestamp()  # For sorting as a number
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

    # data-order attributes provide the raw numeric values for sorting.
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

    Args:
        org_name: The GitHub organization name.
        token: The GitHub authentication token.

    Returns:
        A list of dictionaries, each containing repository data.
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
def aggregate_contributor_data(repos_data: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """
    Aggregate open issues and pull requests counts per contributor across repositories.

    Args:
        repos_data: A list of repository data dictionaries.

    Returns:
        A dictionary mapping contributor login to counts of open issues and PRs.
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
def generate_contrib_table(contrib_data: Dict[str, Dict[str, int]], org_name: str) -> str:
    """
    Generate an HTML table for contributors sorted by the number of open issues and pull requests.

    Args:
        contrib_data: A dictionary of aggregated contributor data.
        org_name: The GitHub organization name.

    Returns:
        A string containing the HTML table.
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
        author_link:str = f"<a href='https://github.com/{login}' target='_blank'>👤 {login}</a>"
        # Include data-order to use raw numeric values for sorting.
        row: str = (
            f"<tr>"
            f"<td data-order='{login}>{author_link}</td>"
            f"<td data-order='{counts['issues']}'>{issues_link}</td>"
            f"<td data-order='{counts['prs']}'>{prs_link}</td>"
            f"</tr>"
        )
        rows.append(row)
    footer: str = "</tbody></table>"
    return header + "\n".join(rows) + footer


@timeit
def load_template(filepath: str) -> str:
    """
    Load and return the contents of the HTML template file.

    Args:
        filepath: The path to the template file.

    Returns:
        The content of the template file as a string.
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

    Args:
        filepath: The path to the output file.
        content: The content to be written.
    """
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"{filepath} generated successfully.")
    except Exception as e:
        log_and_exit(f"Error writing {filepath}: {e}")


@timeit
def main() -> None:
    """
    Main function to generate the repository dashboard HTML using GitHub's GraphQL API.

    It fetches repositories, paginates issues and pull requests, aggregates contributor data,
    generates HTML tables, and writes the final output to index.html.
    """
    token: str = (
            os.environ.get("INPUT_GITHUB_TOKEN")
            or os.environ.get("GITHUB_TOKEN")
            or "your_graphql_token_here"
    )
    org_name: str = os.environ.get("INPUT_ORG_NAME") or os.environ.get("ORG_NAME") or "openfoodfacts"
    if not token or not org_name:
        log_and_exit("GITHUB_TOKEN (or INPUT_GITHUB_TOKEN) and ORG_NAME (or INPUT_ORG_NAME) must be set.")

    repos_data: List[Dict[str, Any]] = fetch_repositories(org_name, token)

    for repo in repos_data:
        owner: str = org_name  # Assuming the owner is the organization.
        issues_data: Dict[str, Any] = repo.get("issues", {})
        total_issues: int = issues_data.get("totalCount", 0)
        current_issues: List[Any] = issues_data.get("nodes", [])
        if total_issues > len(current_issues):
            all_issue_nodes: List[Dict[str, Any]] = fetch_all_issue_nodes(owner, repo["name"], token)
            repo["issues"]["nodes"] = all_issue_nodes
            logger.debug(f"Fetched all {len(all_issue_nodes)} issues for repository {repo['name']}.")
        prs_data: Dict[str, Any] = repo.get("pullRequests", {})
        total_prs: int = prs_data.get("totalCount", 0)
        current_prs: List[Any] = prs_data.get("nodes", [])
        if total_prs > len(current_prs):
            all_pr_nodes: List[Dict[str, Any]] = fetch_all_pr_nodes(owner, repo["name"], token)
            repo["pullRequests"]["nodes"] = all_pr_nodes
            logger.debug(f"Fetched all {len(all_pr_nodes)} pull requests for repository {repo['name']}.")

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

    contrib_data: Dict[str, Dict[str, int]] = aggregate_contributor_data(repos_data)
    html_contrib_table: str = generate_contrib_table(contrib_data, org_name)

    template: str = load_template("template.html")
    last_updated: str = datetime.now(timezone.utc).astimezone().strftime("%m/%d/%Y at %I:%M:%S %p")
    output_html: str = template.replace("{{REPO_TABLE}}", html_repo_table)
    output_html = output_html.replace("{{CONTRIB_TABLE}}", html_contrib_table)
    output_html = output_html.replace("{{LAST_UPDATED}}", last_updated)

    write_output_file("index.html", output_html)


if __name__ == "__main__":
    main()
