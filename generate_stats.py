#!/usr/bin/env python3
"""
generate_stats.py

Pulls live stats for a GitHub user (repos, stars, commits, followers,
lines of code added/removed), combines them with the personal details in
config/profile.env, and stamps everything into the neofetch-style SVG
templates in templates/, producing dark_mode.svg and light_mode.svg in
the repo root.

Nothing in this file needs editing. Personal details (name, contact info,
languages, etc.) live in config/profile.env - edit that instead.

Required env var:
  GH_TOKEN / ACCESS_TOKEN - a classic Personal Access Token with `repo` +
                  `read:user` scopes (the default GITHUB_TOKEN can't read
                  your other repos or your private contribution history).

Optional env vars:
  EXCLUDE_REPOS - comma-separated "owner/name" entries to skip, on top of
                  the profile repo itself (which is always excluded).
  EXCLUDE_FORKS - "true" (default) to skip forked repos when summing
                  stars / lines of code.
"""

import os
import sys
import time
import html
import fnmatch
from datetime import datetime, timezone

import requests

API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"
CONFIG_PATH = "config/profile.env"


def load_config(path):
    """Parse the plain KEY=value config file. Blank lines and lines
    starting with # are ignored."""
    cfg = {}
    if not os.path.exists(path):
        sys.exit(f"Missing {path} - copy config/profile.env and fill it in.")
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            cfg[key.strip()] = val.strip()
    return cfg


CONFIG = load_config(CONFIG_PATH)

TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("ACCESS_TOKEN")
USERNAME = os.environ.get("GH_USERNAME") or CONFIG.get("GITHUB_USERNAME")

if not TOKEN:
    sys.exit("GH_TOKEN (or ACCESS_TOKEN) must be set as an environment variable")
if not USERNAME or USERNAME == "your-username":
    sys.exit(f"Set GITHUB_USERNAME in {CONFIG_PATH} to your real GitHub username")

EXCLUDE_REPOS = [f"{USERNAME}/{USERNAME}"] + [
    r.strip() for r in os.environ.get("EXCLUDE_REPOS", "").split(",") if r.strip()
]
EXCLUDE_FORKS = os.environ.get("EXCLUDE_FORKS", "true").lower() != "false"

SESSION = requests.Session()
SESSION.headers.update(
    {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
)


def is_excluded(full_name: str) -> bool:
    return any(fnmatch.fnmatch(full_name, pat) for pat in EXCLUDE_REPOS)


def get_user():
    r = SESSION.get(f"{API}/users/{USERNAME}")
    r.raise_for_status()
    return r.json()


def get_owned_repos():
    """All repos the authenticated token can see that are owned by USERNAME
    (includes private repos, since the PAT belongs to the same account)."""
    repos, page = [], 1
    while True:
        r = SESSION.get(
            f"{API}/user/repos",
            params={"per_page": 100, "page": page, "affiliation": "owner"},
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        repos.extend(batch)
        page += 1
    return [
        repo
        for repo in repos
        if repo["owner"]["login"].lower() == USERNAME.lower()
        and not is_excluded(repo["full_name"])
        and not (EXCLUDE_FORKS and repo.get("fork"))
    ]


def graphql(query, variables=None):
    r = SESSION.post(GRAPHQL, json={"query": query, "variables": variables or {}})
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        print("GraphQL errors:", data["errors"], file=sys.stderr)
    return data.get("data", {})


def get_contributed_repo_count():
    q = """
    query {
      viewer {
        repositoriesContributedTo(first: 1, includeUserRepositories: false,
          contributionTypes: [COMMIT, PULL_REQUEST, ISSUE]) {
          totalCount
        }
      }
    }
    """
    data = graphql(q)
    return data.get("viewer", {}).get("repositoriesContributedTo", {}).get(
        "totalCount", 0
    )


def get_total_commits(created_at: str):
    start_year = datetime.fromisoformat(created_at.replace("Z", "+00:00")).year
    end_year = datetime.now(timezone.utc).year
    total = 0
    q = """
    query($from: DateTime!, $to: DateTime!) {
      viewer {
        contributionsCollection(from: $from, to: $to) {
          totalCommitContributions
          restrictedContributionsCount
        }
      }
    }
    """
    for year in range(start_year, end_year + 1):
        frm = f"{year}-01-01T00:00:00Z"
        to = f"{year}-12-31T23:59:59Z"
        data = graphql(q, {"from": frm, "to": to})
        cc = data.get("viewer", {}).get("contributionsCollection", {})
        total += cc.get("totalCommitContributions", 0)
        total += cc.get("restrictedContributionsCount", 0)
    return total


def get_lines_of_code(repos):
    """Sum additions/deletions attributed to USERNAME across repos, via the
    stats/contributors endpoint (same source GitHub's own contribution
    graphs use). GitHub computes this async, so a fresh repo can return 202
    ('still computing') - retry a few times."""
    additions = deletions = 0
    for repo in repos:
        full_name = repo["full_name"]
        for attempt in range(6):
            r = SESSION.get(f"{API}/repos/{full_name}/stats/contributors")
            if r.status_code == 202:
                time.sleep(2)
                continue
            if r.status_code != 200:
                break
            for entry in r.json() or []:
                if (entry.get("author") or {}).get("login", "").lower() == USERNAME.lower():
                    for week in entry.get("weeks", []):
                        additions += week.get("a", 0)
                        deletions += week.get("d", 0)
            break
    return additions, deletions


def fmt(n):
    n = int(n)
    if abs(n) >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if abs(n) >= 1_000:
        return f"{n/1_000:.1f}K".replace(".0K", "K")
    return str(n)


def fmt_int(n):
    return f"{int(n):,}"


def uptime_string(created_at: str):
    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    days_total = (now - created).days
    years, rem_days = divmod(days_total, 365)
    months = rem_days // 30
    days = rem_days % 30
    return f"{years} years, {months} months, {days} days"


def main():
    print(f"Collecting stats for {USERNAME}...")
    user = get_user()
    owned_repos = get_owned_repos()
    print(f"  owned repos counted: {len(owned_repos)}")

    stars = sum(r.get("stargazers_count", 0) for r in owned_repos)
    contributed = get_contributed_repo_count()
    commits = get_total_commits(user["created_at"])
    additions, deletions = get_lines_of_code(owned_repos)
    net = additions - deletions

    # Personal/content fields from config/profile.env (escaped so stray
    # &, <, > in someone's text can't break the SVG's XML).
    values = {k: html.escape(v, quote=False) for k, v in CONFIG.items()}

    # Live GitHub stats overwrite/add to that.
    values.update(
        {
            "GITHUB_USERNAME": USERNAME,
            "UPTIME": uptime_string(user["created_at"]),
            "REPOS": str(user.get("public_repos", len(owned_repos))),
            "CONTRIB": str(contributed),
            "STARS": fmt_int(stars),
            "COMMITS": fmt_int(commits),
            "FOLLOWERS": fmt_int(user.get("followers", 0)),
            "LOC_NET": fmt(net),
            "LOC_ADD": fmt(additions),
            "LOC_DEL": fmt(deletions),
        }
    )
    print("  values:", values)

    for theme in ("dark", "light"):
        with open(f"templates/overview_{theme}.svg", encoding="utf-8") as f:
            svg = f.read()
        for key, val in values.items():
            svg = svg.replace("{{" + key + "}}", val)
        out_name = "dark_mode.svg" if theme == "dark" else "light_mode.svg"
        with open(out_name, "w", encoding="utf-8") as f:
            f.write(svg)
        print(f"  wrote {out_name}")


if __name__ == "__main__":
    main()
