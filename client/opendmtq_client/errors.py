"""Errors that a person reads.

An error keeps its English sentence, str(e), which the command line and the logs show. For the launcher's window it
also carries a key into i18n.TEXT and the values for the gaps, so a reader who picked Korean reads it in Korean. An
error with no key, or a key missing from the words, reads as its English sentence.

A failure that comes as another program's own words (Velopack's, the system's) is said by its kind instead (fault): no
network, no answer, a full disk, a file in use, no permission, or anything else; those words stay in the log.
"""

import re


class Worded(Exception):
    """An exception with an English sentence and, optionally, the key and values of its words in i18n.TEXT."""

    def __init__(self, message, key=None, **params):
        super().__init__(message)
        # The key picks the words; the params fill their {gaps}.
        self.key, self.params = key, params


# Each kind of failure a person can do something about, by the marks of it in the words a program gives: Windows' error
# numbers as Velopack and Python write them ("os error 112", "[WinError 5]"), Windows' and Linux's own sentences
# (Wine says Windows' numbers, the tests Linux's), and Velopack's and its web library's (ureq) names. The first kind
# whose marks are found is the one; the order puts the disk and the files before the network, as a full disk during a
# download is still a full disk.
FAULTS = (
    # Velopack's setup says a disk short of room before it begins as "OpenDMTQ requires at least 187.19 MB disk space
    # to be installed. There is only 57.59 MB available."
    ("disk_full", re.compile(r"(os|win)\s?error\]? (112|39)\b|errno 28\b|not enough space|no space left|disk (is )?full"
                             r"|insufficient (disk )?space|requires at least .* disk space", re.I)),
    ("in_use", re.compile(r"(os|win)\s?error\]? (32|33)\b|errno (16|26)\b|being used by another process"
                          r"|text file busy|resource busy|\bin use\b", re.I)),
    ("denied", re.compile(r"(os|win)\s?error\]? 5\b|errno (1|13)\b|access is denied|permission denied"
                          r"|operation not permitted", re.I)),
    ("network", re.compile(r"(os|win)\s?error\]? (11001|11002|11003|11004|10050|10051|10065)\b"
                           r"|host not found|no such host|name or service not known|name resolution"
                           r"|nodename nor servname|network is unreachable|failed to lookup address", re.I)),
    ("no_answer", re.compile(r"(os|win)\s?error\]? (10060|10061)\b|timed out|timeout|connection refused"
                             r"|actively refused|did not properly respond", re.I)),
)
# The kinds that come only from asking something over the network: a program that asks nothing (Velopack's setup, which
# installs from the installer's own file) never fails for them, so its words are never read as one of them.
NETWORK_FAULTS = ("network", "no_answer")


def fault(failure, network=True):
    """The kind of a failure (an exception, or a program's own words for it): "disk_full", "in_use", "denied",
    "network" or "no_answer"; None for anything else, which the plain words leave to the log. `network` False for work
    that asks nothing over the network."""
    text = str(failure or "")
    for kind, marks in FAULTS:
        if (network or kind not in NETWORK_FAULTS) and marks.search(text):
            return kind
    return None
