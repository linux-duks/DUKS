import logging
import os
import sys
import re
import csv
from datetime import datetime, timedelta
from collections import deque

import orjson
import grpc
import swh.graph.grpc.swhgraph_pb2 as swhgraph
import swh.graph.grpc.swhgraph_pb2_grpc as swhgraph_grpc
# from google.protobuf.field_mask_pb2 import FieldMask


GRAPH_GRPC_SERVER = "0.0.0.0:50091"
LIMIT = 0
PRE_LOAD_COMMITS_FROM = os.getenv("PRE_LOAD_COMMITS_FROM_STDIN", "false") != "false"
# defaults to the last commit available in the swh exported graph
INITIAL_NODE = os.getenv(
    "INITIAL_NODE", "swh:1:rev:4a2d78822fdf1556dfbbfaedd71182fe5b562194"
)

DEBUG = os.getenv("DEBUG", "false")
level = logging.INFO
if DEBUG != "false":
    level = logging.DEBUG

logging.basicConfig(
    level=level,
    format="[%(asctime)s] {%(pathname)s:%(lineno)d} %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)


# UniqueDeque is a queue with a HashSet to guarantee uniqueness in queued items
class UniqueDeque:
    def __init__(self, iterable=None):
        self._deque = deque()
        self._set = set()
        if iterable:
            for item in iterable:
                self.append(item)

    def append(self, item):
        if item not in self._set:
            self._deque.append(item)
            self._set.add(item)

    def appendleft(self, item):
        if item not in self._set:
            self._deque.appendleft(item)
            self._set.add(item)

    def pop(self):
        item = self._deque.pop()
        self._set.remove(item)
        return item

    def popleft(self):
        item = self._deque.popleft()
        self._set.remove(item)
        return item

    def __len__(self):
        return len(self._deque)

    def __iter__(self):
        return iter(self._deque)

    def __repr__(self):
        return f"UniqueDeque({list(self._deque)})"


def extract_attributions(commit_message) -> (list[dict], list[str]):
    """
    Parses a git commit message and extracts all personal attributions.

    Args:
        commit_message (str): The full git commit message.

    Returns:
        list: A list of dictionaries, where each dictionary contains
              'type' (e.g., 'Signed-off-by'), 'name', and 'email' for each attribution found.
    """
    attributions = []
    # This regex looks for lines starting with "Word-by:"
    # followed by a name (can contain various characters), and then an email in angle brackets.
    # It captures the "Word-by" type, the name, and the email separately.
    # The pattern is compiled with MULTILINE to match '^' at the start of each line,
    # and IGNORECASE to match "Signed-off-by", "signed-off-by", etc.
    pattern = re.compile(
        r"^(?P<type>[a-zA-Z\-]+-by):\s*(?P<name>[^<]+?)\s*<(?P<email>[^>]+)>",
        re.MULTILINE | re.IGNORECASE,
    )

    # Use finditer to get all non-overlapping matches
    for match in pattern.finditer(commit_message):
        attributions.append(
            {
                "type": match.group(
                    "type"
                ).strip(),  # Extract the attribution type (e.g., 'Signed-off-by')
                "name": match.group(
                    "name"
                ).strip(),  # Extract the name (e.g., 'Author Name')
                "email": match.group(
                    "email"
                ).strip(),  # Extract the email (e.g., 'author.name@email.com')
            }
        )
    return attributions


# def extract_links(commit_message):
#     """
#     Parses a git commit message and extracts all URLs (links).
#
#     Args:
#         commit_message (str): The full git commit message.
#
#     Returns:
#         list: A list of strings, where each string is a URL found in the message.
#     """
#     links = []
#     # This regex looks for common URL patterns starting with http or https.
#     # It captures the full URL.
#     # The pattern is non-greedy to avoid capturing too much if multiple links are on a line.
#     pattern = re.compile(
#         r"https?://[^\s<>\"'{}|\\^`[\]]+",
#         re.IGNORECASE
#     )
#
#     # Use findall to get all non-overlapping matches as a list of strings
#     links = pattern.findall(commit_message)
#     return links


def write_commit(writer: csv.writer, current_node_response):
    attributions = extract_attributions(str(current_node_response.rev.message.decode()))

    writer.writerow(
        [
            # commit sha1
            current_node_response.swhid.lstrip("swh:1:rev:"),
            # all successor ids
            # orjson.dumps(
            #     [
            #         succ.swhid.lstrip("swh:1:rev")
            #         for succ in current_node_response.successor
            #         if succ.swhid.startswith("swh:1:rev")
            #     ]
            # ).decode(),  # parents
            (
                datetime.utcfromtimestamp(current_node_response.rev.committer_date)
                + timedelta(minutes=current_node_response.rev.committer_date_offset)
            ).strftime("%Y-%m-%dT%H:%M:%S"),  # committer_date
            (
                datetime.utcfromtimestamp(current_node_response.rev.author_date)
                + timedelta(minutes=current_node_response.rev.author_date_offset)
            ).strftime("%Y-%m-%dT%H:%M:%S"),  # author_date
            orjson.dumps(
                attributions
            ).decode(),  # attributions: dict with authors, acks, reviews...
            # diffs when available in the graph
            # 0,
            # 0,
        ]
    )


def main():
    file = open("../data/file.csv", "w", newline="", buffering=1, encoding="utf-8")
    writer = csv.writer(file, delimiter="|", quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(
        [
            "commit",
            # "parents",
            "committer_date",
            "author_date",
            "attributions",
            # "diff_plus",
            # "diff_minus",
        ]
    )

    node_num = 0
    visited = set()
    queue = UniqueDeque([INITIAL_NODE])

    # can be used with :
    # $ tail -n +2 file.csv | awk -F'|' '{print $1}' | PRE_LOAD_COMMITS_FROM_STDIN=true uv run python grpc_script.py
    # skip the header line  | print only the first column

    if PRE_LOAD_COMMITS_FROM:
        logging.info("Reading existing visited nodes")
        last_node = None
        for line in sys.stdin:
            last_node = "swh:1:rev:{}".format(line.strip().strip('"'))
            visited.add(last_node)
        logging.info(f"LastNode read from stdin: {last_node}")
        queue = UniqueDeque([last_node])

    with grpc.insecure_channel(GRAPH_GRPC_SERVER) as channel:
        stub = swhgraph_grpc.TraversalServiceStub(channel)

        logging.info(f"Preparing BFS with {queue}")
        while queue:
            try:
                current_node = queue.popleft()
                logging.debug(f"Popped {current_node}")

                if current_node not in visited:
                    visited.add(current_node)
                    logging.info(f"Visiting {current_node}")

                    # GetNode details from graph
                    current_node_response = stub.GetNode(
                        swhgraph.GetNodeRequest(
                            swhid=current_node,
                            # mask=FieldMask(paths=["swhid", "rev.message", "rev.author"]),
                        )
                    )

                    # logging.debug(f"Current node response: {current_node_response}")
                    node_num += 1

                    for succ in current_node_response.successor:
                        logging.debug(f"successor: {succ}")
                        # filter only revisions
                        if (
                            succ.swhid.startswith("swh:1:rev")
                            and succ.swhid not in visited
                        ):
                            queue.append(succ.swhid)
                        # else:
                        #     print("READING NODE", succ)
                        #     dir_current_node_response = stub.GetNode(
                        #         swhgraph.GetNodeRequest(
                        #             swhid=succ_swhid,
                        #             # mask=FieldMask(paths=["swhid", "rev.message", "rev.author"]),
                        #         )
                        #     )
                        #     print(dir_current_node_response)

                    # add current commit to writer
                    write_commit(writer, current_node_response)

            except Exception as e:
                logging.error(e)
                break

            if node_num > LIMIT and LIMIT > 0:
                break
    file.close()


if __name__ == "__main__":
    main()
