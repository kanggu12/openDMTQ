"""Errors that a person reads.

An error keeps its English sentence, str(e), which the command line and the logs show. For the launcher's window it
also carries a key into i18n.TEXT and the values for the gaps, so a reader who picked Korean reads it in Korean. An
error with no key, or a key missing from the words, reads as its English sentence.
"""


class Worded(Exception):
    """An exception with an English sentence and, optionally, the key and values of its words in i18n.TEXT."""

    def __init__(self, message, key=None, **params):
        super().__init__(message)
        # The key picks the words; the params fill their {gaps}.
        self.key, self.params = key, params
