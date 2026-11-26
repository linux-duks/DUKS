import logging
import os
import sys
import re
import csv
from datetime import datetime, timedelta
from collections import deque
import hashlib

import orjson
import grpc
import swh.graph.grpc.swhgraph_pb2 as swhgraph
import swh.graph.grpc.swhgraph_pb2_grpc as swhgraph_grpc

# from google.protobuf.field_mask_pb2 import FieldMask
# from google.protobuf.json_format import MessageToDict


# limit for debug purposes
LIMIT = 0
GRAPH_GRPC_SERVER = os.getenv("GRAPH_GRPC_SERVER", "0.0.0.0:50091")
PRE_LOAD_COMMITS_FROM = os.getenv("PRE_LOAD_COMMITS_FROM_STDIN", "false") != "false"
KERNEL_TREE = os.getenv(
    "KERNEL_TREE", "git://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git"
)
# defaults to the last commit available in the swh exported graph
# if provided, the script will skip searching by origin (kernel tree)
INITIAL_NODE = os.getenv("INITIAL_NODE", "")
DEFAULT_BRANCH = os.getenv("DEFAULT_BRANCH", "master")

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


def extract_attributions(commit_message) -> list[dict]:
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


# there are messages with non utf8 encoding
# this will try to decode them in utf8, cp1252 utf8 with replace (? char), or ignore with empty string
def decode_message(swhid: str, input_message: bytes) -> str:
    message = ""
    try:
        message = input_message.decode("utf-8")
    except Exception as e:
        logging.error(
            f"Failed to decode node message with unicode: {swhid}, message: {input_message}, error: {e}"
        )
        try:
            message = input_message.decode(encoding="cp1252")
        except Exception as e:
            logging.error(
                f"Failed to decode node message with cp1252: {swhid}, message: {input_message}, error: {e}"
            )
            try:
                message = input_message.decode("utf-8", errors="replace")
            except Exception as e:
                logging.error(
                    f"Failed to decode node message with utf-8 using replace mode: {swhid}, message: {input_message}, error: {e}"
                )
                # if even replace fails, ignore the message
                message = ""
    return message


def write_commit(writer, current_node_response, tag_map):
    attributions = extract_attributions(
        decode_message(current_node_response.swhid, current_node_response.rev.message)
    )
    commit_sha1 = current_node_response.swhid.lstrip("swh:1:rev:")
    tag = tag_map.get(commit_sha1)
    writer.writerow(
        [
            # commit sha1
            commit_sha1,
            # committer_date
            (
                datetime.utcfromtimestamp(current_node_response.rev.committer_date)
                + timedelta(minutes=current_node_response.rev.committer_date_offset)
            ).strftime("%Y-%m-%dT%H:%M:%S"),
            # author_date
            (
                datetime.utcfromtimestamp(current_node_response.rev.author_date)
                + timedelta(minutes=current_node_response.rev.author_date_offset)
            ).strftime("%Y-%m-%dT%H:%M:%S"),
            # attributions: dict with authors, acks, reviews...
            orjson.dumps(attributions).decode(),
            tag,
            # diffs when available in the graph
            # 0,
            # 0,
        ]
    )


def main():
    # Kernel exports live in their own module folder under the shared data root
    # (see server/data_dirs.py); create it on a fresh checkout.
    try:
        os.makedirs("./data/kernel", exist_ok=True)
        # pi-lens-ignore: SIM115 -- closed at the end of the BFS traversal.
        file = open(
            "./data/kernel/commits.csv", "w", newline="", buffering=1, encoding="utf-8"
        )
    except OSError as exc:
        logging.error("cannot write ./data/kernel/commits.csv: %s", exc)
        return
    writer = csv.writer(file, delimiter="|", quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(
        [
            "commit",
            "committer_date",
            "author_date",
            "attributions",
            "tag",
            # "diff_plus",
            # "diff_minus",
        ]
    )

    node_num = 0
    visited = set()
    queue = UniqueDeque()

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

        origin_sha1 = hashlib.sha1(KERNEL_TREE.encode("utf-8")).hexdigest()

        # or look for initial node, by loading the ORIGIN
        # load releases and last commit from origin
        origin_node = stub.GetNode(
            swhgraph.GetNodeRequest(
                swhid=f"swh:1:ori:{origin_sha1}",
                # mask=FieldMask(paths=["swhid", "rev.message", "rev.author"]),
            )
        )
        # print(origin_node)
        # get the last snapshot
        last_snapshot = None
        for succ in origin_node.successor:
            if last_snapshot is None:
                last_snapshot = succ
            else:
                # TODO: check if there are other labels
                visit_timestamp = last_snapshot.label[0].visit_timestamp
                suucc_timestamp = succ.label[0].visit_timestamp
                if suucc_timestamp > visit_timestamp:
                    last_snapshot = succ
        if last_snapshot is None:
            logging.error("no snapshot found for origin %s", KERNEL_TREE)
            file.close()
            return
        last_snapshot = stub.GetNode(
            swhgraph.GetNodeRequest(
                swhid=last_snapshot.swhid,
            )
        )
        rev_rel_map = {}

        logging.info("Looking for starting commit and building release map")

        for succ in last_snapshot.successor:
            # if succ.swhid.startswith("swh:1:rev"):
            if succ.swhid.startswith("swh:1:rev") and succ.label[
                0
            ].name.decode().endswith(DEFAULT_BRANCH):
                print(f"INITIAL_NODE will be {succ}, {succ.label[0].name.decode()}")
                queue.append(succ.swhid)
            # TODO: pick commits from other branches too ?

            elif succ.swhid.startswith("swh:1:rel"):
                tag = stub.GetNode(
                    swhgraph.GetNodeRequest(
                        swhid=succ.swhid,
                    )
                )

                for succ in tag.successor:
                    rev_rel_map[succ.swhid.lstrip("swh:1:rev:")] = tag.rel.name.decode(
                        "utf-8"
                    )
            # print(rev_rel_map)
            # print(last_snapshot)

        # start from INITIAL_NODE if set
        if INITIAL_NODE:
            queue = UniqueDeque([INITIAL_NODE])

        logging.info(f"Preparing BFS with {queue}")
        while queue:
            try:
                current_node = queue.popleft()
                logging.debug(f"Popped {current_node}")

                if current_node not in visited:
                    visited.add(current_node)
                    logging.info(f"Visiting {current_node}")

                    try:
                        # GetNode details from graph
                        current_node_response = stub.GetNode(
                            swhgraph.GetNodeRequest(
                                swhid=current_node,
                                # mask=FieldMask(paths=["swhid", "rev.message", "rev.author"]),
                            )
                        )
                    except Exception as e:
                        logging.exception(
                            f"skipped node {current_node}  because of exception: {e}"
                        )
                        continue

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
                        elif DEBUG != "false" and succ.swhid not in visited:
                            logging.debug(f"Found a non-revision node: {succ.swhid}")
                            if not succ.swhid.startswith("swh:1:dir"):
                                nodeInfo = stub.GetNode(
                                    swhgraph.GetNodeRequest(
                                        swhid=succ.swhid,
                                        # mask=FieldMask(paths=["swhid", "rev.message", "rev.author"]),
                                    )
                                )
                                logging.debug(
                                    f"Non dir/revision node found: {nodeInfo}"
                                )

                    # add current commit to writer
                    write_commit(writer, current_node_response, rev_rel_map)

            except Exception as e:
                logging.exception(e)
                break

            if node_num > LIMIT and LIMIT > 0:
                break
    file.close()


if __name__ == "__main__":
    main()
