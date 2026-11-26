import logging
import subprocess
import csv
import orjson
import os
import re
from datetime import datetime

from pygit2 import Commit, Repository

kernel_path = os.getenv("KERNEL_PATH", ".")

LOAD_TAGS_FROM_REPO = os.getenv("LOAD_TAGS_FROM_REPO", "false") != "false"
DEBUG = os.getenv("DEBUG", "false")
level = logging.INFO
if DEBUG != "false":
    level = logging.DEBUG

logging.basicConfig(
    level=level,
    format="[%(asctime)s] {%(pathname)s:%(lineno)d} %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)


def fix_attributions(attributions, author, committer):
    attrs = orjson.loads(attributions)
    new_attrs_block = []

    for attr in attrs:
        # remove author and committer duplicate
        if (
            attr.get("email")
            and attr["email"] != author.email
            and attr["email"] != committer.email
        ):
            new_attrs_block.append(attr)
    return orjson.dumps(new_attrs_block).decode()


def read_tags(repo: Repository) -> list[list[str | datetime | None]]:
    tags_result = subprocess.run(
        ["git", "show-ref", "--tags", "-d"],
        cwd=repo.workdir,
        capture_output=True,
        text=True,
    )
    if tags_result.returncode != 0:
        logging.error(tags_result.stderr)
        return []
    tags = tags_result.stdout.strip().split("\n")
    tags.reverse()
    tag_list = []

    # the desired tags are in this formats: v6.9^{}" or v6.9
    regex = re.compile(r"v(\d+(?:\.\d+)*)(\^{})?")

    for tag_line in tags:
        sha, tag = tag_line.split(" ")
        tag_version = ""

        # ignore release candidate tags
        if "-rc" not in tag:
            match = regex.search(tag)
            if match:
                try:
                    commit = repo.get(sha)
                    commit_time = None
                    # Lightweight tags point straight at the commit; annotated
                    # ones are peeled by `git show-ref -d`, so anything that is
                    # not a commit here is a git oddity worth skipping.
                    if isinstance(commit, Commit):
                        commit_time = datetime.fromtimestamp(commit.commit_time)
                    else:
                        logging.info("%s git object is probably not a commit", sha)
                    tag_version = match.group(1)
                    tag_list.append(
                        [
                            tag_version,
                            sha,
                            commit_time,
                        ]
                    )
                except Exception as e:
                    logging.error(e)
                    pass

    return tag_list


def write_tags_file(tags: list[list[str | datetime | None]]):
    try:
        # pi-lens-ignore: SIM115 -- the handle is closed once every tag is written.
        tags_file = open(
            "./data/kernel/tags.csv", "w", newline="", buffering=1, encoding="utf-8"
        )
    except OSError as exc:
        logging.error("cannot write ./data/kernel/tags.csv: %s", exc)
        return
    tags_writer = csv.writer(
        tags_file, delimiter="|", quoting=csv.QUOTE_ALL, lineterminator="\n"
    )

    tags_writer.writerow(["tag", "commit", "date"])

    for tag_line in tags:
        tags_writer.writerow(tag_line)


def run(kernel_path: str):
    INITIAL_COMMIT = "4a2d78822fdf1556dfbbfaedd71182fe5b562194"

    logging.info(f"Reading from kernel located at : {kernel_path}")
    repo = Repository(kernel_path)
    repo.get(INITIAL_COMMIT)

    try:
        # pi-lens-ignore: SIM115 -- both handles stay open for the whole export loop.
        commits_file = open("./data/kernel/commits.csv")
        # pi-lens-ignore: SIM115
        file = open(
            "./data/kernel/enhanced.csv", "w", newline="", buffering=1, encoding="utf-8"
        )
    except OSError as exc:
        # commits.csv is produced by grpc_script.py; enhanced.csv is our output.
        logging.error("cannot open the kernel export files: %s", exc)
        return
    reader = csv.DictReader(commits_file, delimiter="|")
    writer = csv.writer(file, delimiter="|", quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(
        [
            "commit",
            "committer_date",
            "author_date",
            "insertions",
            "deletions",
            "author",
            "committer",
            "attributions",
            "tag",
        ]
    )

    tag_map = {}
    if LOAD_TAGS_FROM_REPO:
        # read all tags from repo
        tags = read_tags(repo)
        # write a tag:commit csv file
        write_tags_file(tags)

        # map commit:tag for reverse lookup
        tag_map = {tagl[1]: tagl[0] for tagl in tags}

    for row in reader:
        commit = repo.get(row["commit"])
        if isinstance(commit, Commit):
            parents = commit.parents

            # merge commits default to 0 (should be accounted by the commits themselves)
            insertions = 0
            deletions = 0

            # more than one parent indicates a merge commit
            if len(parents) == 1:
                parent = parents[0]
                if parent is not None:
                    diff = repo.diff(commit.id, parent.id)
                    insertions = diff.stats.insertions
                    deletions = diff.stats.deletions

            writer.writerow(
                [
                    row["commit"],
                    # row["parents"],
                    row["committer_date"],
                    row["author_date"],
                    insertions,
                    deletions,
                    commit.author.email,
                    commit.committer.email,
                    fix_attributions(
                        row["attributions"], commit.author, commit.committer
                    ),
                    # load tag from original file or from Repository
                    tag_map.get(row["commit"])
                    if LOAD_TAGS_FROM_REPO
                    else row.get("tag"),
                ]
            )

    file.close()


if __name__ == "__main__":
    run(kernel_path)
