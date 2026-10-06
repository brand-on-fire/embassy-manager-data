#!/usr/bin/env python3
"""Public data branch transport. GitHub-hosted public workflow only; no local activation."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
from urllib.request import Request, urlopen

REPOSITORY = "brand-on-fire/embassy-manager-data"
BRANCH = "public-data"
MAX_PAYLOAD = 10 * 1024 * 1024
MAX_REPOSITORY = 200 * 1024 * 1024


def run(*args, env=None):
    return subprocess.run(args, check=True, capture_output=True, env=env).stdout


def allowed(path):
    return path in ("manifest.json", "review-queue.json", "collector-state/state.json") or bool(re.fullmatch(r"(?:editions/[a-z0-9-]+|collector-state/(?:sources|editions)/[a-z0-9-]+)/[a-f0-9]{64}\.json", path))


def check_context():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_REPOSITORY") != REPOSITORY or os.environ.get("GITHUB_EVENT_NAME") not in ("schedule", "workflow_dispatch", "push") or os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise ValueError("Publication is restricted to the approved public GitHub workflow")
    request = Request("https://api.github.com/repos/" + REPOSITORY, headers={"Accept": "application/vnd.github+json", "User-Agent": "EmbassyManagerPublicCollector/1"})
    with urlopen(request, timeout=10) as response:
        body = response.read(100001)
    if len(body) > 100000:
        raise ValueError("Repository response exceeds its complete-response limit")
    repository = json.loads(body)
    if repository.get("full_name") != REPOSITORY or repository.get("private") is not False or repository.get("visibility") != "public" or type(repository.get("size")) is not int:
        raise ValueError("Fresh public repository visibility and size must be established")
    return repository["size"] * 1024


def storage_guard(generated, provider_size, git_directory, maximum=MAX_REPOSITORY):
    payload = 0
    for path in generated.rglob("*"):
        if path.is_symlink():
            raise ValueError("Symbolic links are forbidden in public data")
        if path.is_file():
            if not allowed(path.relative_to(generated).as_posix()):
                raise ValueError("Unexpected generated publication file")
            payload += path.stat().st_size
            json.loads(path.read_text())
    manifest = json.loads((generated / "manifest.json").read_text())
    if set(manifest) != {"schemaVersion", "generatedAt", "posts"} or manifest["schemaVersion"] != 1 or len(manifest["posts"]) > 300:
        raise ValueError("Invalid public manifest")
    post_ids = set()
    for entry in manifest["posts"]:
        if set(entry) != {"postId", "path", "sha256", "bytes"} or not re.fullmatch(r"[a-z0-9-]+", entry["postId"]) or entry["postId"] in post_ids or not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"]):
            raise ValueError("Invalid or repeated manifest entry")
        post_ids.add(entry["postId"])
        if entry["path"] != f"editions/{entry['postId']}/{entry['sha256']}.json":
            raise ValueError("Manifest path is not the exact content-addressed post path")
        body = (generated / entry["path"]).read_bytes()
        if type(entry["bytes"]) is not int or not 1 <= entry["bytes"] <= 500000 or len(body) != entry["bytes"] or hashlib.sha256(body).hexdigest() != entry["sha256"]:
            raise ValueError("Published envelope hash or byte count does not match")
        envelope = json.loads(body)
        if set(envelope) != {"schemaVersion", "postId", "generatedAt", "edition", "sources", "corrections", "collection"} or envelope["schemaVersion"] != 1 or envelope["postId"] != entry["postId"] or envelope["edition"]["postId"] != entry["postId"] or envelope["edition"]["mode"] != "reviewed-public":
            raise ValueError("Unexpected envelope fields or post identity")
    local_git = sum(path.stat().st_size for path in git_directory.rglob("*") if path.is_file() and not path.is_symlink())
    if payload > MAX_PAYLOAD or max(provider_size, local_git) + payload > maximum:
        raise ValueError("MAINTENANCE REQUIRED: publication stopped at its payload/repository storage limit; paid expansion is prohibited")
    return payload


def previous_commit():
    result = subprocess.run(["git", "rev-parse", "--verify", "refs/remotes/origin/" + BRANCH], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def restore(generated, commit):
    generated.mkdir(parents=True, exist_ok=True)
    if any(generated.iterdir()):
        raise ValueError("Restore requires an empty generated directory")
    if not commit:
        return
    archive = run("git", "archive", "--format=tar", commit)
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        members = bundle.getmembers()
        files = [item for item in members if not item.isdir()]
        if any(not item.isfile() or not allowed(item.name) for item in files) or sum(item.size for item in files) > MAX_PAYLOAD:
            raise ValueError("Previous generated branch contains unsupported files or exceeds its cap")
        for item in files:
            target = generated / item.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bundle.extractfile(item).read())


def publish(generated, commit):
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise ValueError("The workflow's ephemeral repository token is required")
    with tempfile.TemporaryDirectory() as directory:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(directory) / "index"), "GIT_WORK_TREE": str(generated.resolve()), "GIT_AUTHOR_NAME": "Embassy public-data collector", "GIT_AUTHOR_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com", "GIT_COMMITTER_NAME": "Embassy public-data collector", "GIT_COMMITTER_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com"}
        run("git", "read-tree", "--empty", env=env)
        run("git", "add", "--all", env=env)
        tree = run("git", "write-tree", env=env).decode().strip()
        if commit and tree == run("git", "rev-parse", commit + "^{tree}").decode().strip():
            print("No generated changes; no commit or push.")
            return
        args = ["git", "commit-tree", tree, "-m", "Update reviewed public collection"]
        if commit:
            args += ["-p", commit]
        new_commit = run(*args, env=env).decode().strip()
        # The token exists only in this process environment, never a file or remote URL.
        push_env = {**env, "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader", "GIT_CONFIG_VALUE_0": "AUTHORIZATION: basic " + base64.b64encode(("x-access-token:" + token).encode()).decode(), "GIT_TERMINAL_PROMPT": "0", "GIT_TRACE": "0", "GIT_TRACE_CURL": "0", "GIT_CURL_VERBOSE": "0"}
        run("git", "push", "https://github.com/" + REPOSITORY + ".git", new_commit + ":refs/heads/" + BRANCH, env=push_env)
        print("Updated the public-data branch with an ordinary commit.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("restore", "publish"))
    parser.add_argument("--directory", type=Path, default=Path("generated"))
    args = parser.parse_args()
    try:
        size = check_context()
        if size >= MAX_REPOSITORY:
            raise ValueError("MAINTENANCE REQUIRED: repository reached its 200 MiB limit; publication stopped")
        commit = previous_commit()
        if args.command == "restore":
            restore(args.directory, commit)
        else:
            storage_guard(args.directory, size, Path(run("git", "rev-parse", "--git-dir").decode().strip()))
            publish(args.directory, commit)
    except Exception as error:
        # Never print request headers, environment or subprocess stderr.
        message = str(error) if isinstance(error, ValueError) else type(error).__name__
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a") as stream:
                stream.write("Collection publication stopped: " + message + "\n")
        raise SystemExit(message) from None


if __name__ == "__main__":
    main()
