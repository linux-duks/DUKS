import logging
import subprocess
import csv
import orjson
import os

from pygit2 import Repository

kernel_path = os.getenv("KERNEL_PATH", ".")
DEBUG = os.getenv("DEBUG", "false")
level = logging.INFO
if DEBUG != "false":
    level = logging.DEBUG

logging.basicConfig(
    level=level,
    format="[%(asctime)s] {%(pathname)s:%(lineno)d} %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)


def read_maintainers_file_commits(repo: Repository) -> list[str]:
    git_history_result = subprocess.run(
        ["git", "--no-pager", "log", "--follow", '--pretty=format:"%H"', "MAINTAINERS"],
        cwd=repo.workdir,
        capture_output=True,
        text=True,
    )
    if git_history_result.returncode != 0:
        logging.error(git_history_result.stderr)
        return []
    commits = git_history_result.stdout.strip().split("\n")
    return commits


def checkout_and_read_file(repo: Repository, sha: str) -> str | None:
    checkout = subprocess.run(
        ["git", "checkout", sha],
        cwd=repo.workdir,
        capture_output=True,
        text=True,
    )

    if checkout.returncode != 0:
        logging.error(checkout.stderr)
        return None

    maintain_emails = subprocess.run(
        ["awk", "/^M:|^R:/{print $NF}", "MAINTAINERS"],
        cwd=repo.workdir,
        capture_output=True,
        text=True,
    )
    if maintain_emails.returncode != 0:
        logging.error(maintain_emails.stderr)
        return None
    emails = (
        maintain_emails.stdout.strip().replace("<", "").replace(">", "").split("\n")
    )
    return orjson.dumps(emails).decode()


def run(kernel_path: str):
    # Kernel exports live in their own module folder under the shared data root
    # (see server/data_dirs.py); create it on a fresh checkout.
    try:
        os.makedirs("./data/kernel", exist_ok=True)
        tags_file = open(
            "./data/kernel/maintainers.csv",
            "w",
            newline="",
            buffering=1,
            encoding="utf-8",
        )
    except OSError as exc:
        logging.error("cannot write ./data/kernel/maintainers.csv: %s", exc)
        return
    tags_writer = csv.writer(
        tags_file, delimiter="|", quoting=csv.QUOTE_ALL, lineterminator="\n"
    )

    tags_writer.writerow(["commit", "maintainers"])

    repo = Repository(kernel_path)

    branch = repo.lookup_branch("master")
    ref = repo.lookup_reference(branch.name)
    repo.checkout(ref)

    logging.info("reading all relevant commits")
    commits = read_maintainers_file_commits(repo)

    logging.info("checking out commits")
    for commit in commits:
        emails = checkout_and_read_file(repo, commit.strip().strip('"').strip(""))
        tags_writer.writerow([commit, emails])
        logging.info(f"commit row written: {commit}")
    tags_file.close()


if __name__ == "__main__":
    run(kernel_path)
