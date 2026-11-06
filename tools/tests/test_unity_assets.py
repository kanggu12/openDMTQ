"""The small reader and editor of the game's screen files, on files built here. tests/qa.sh also runs
test_real_client.py, which checks every edit against the real client."""

import struct
import unittest

from opendmtq_tools import unity_assets as ua

# A little hierarchy: Root > Menu > (Button, Other), and a second root with the same child name.
OBJECTS = [
    (1, "Root", 0, True, (0, 0)),
    (2, "Menu", 1, True, (10, 20)),
    (3, "Button", 2, True, (-5, 7)),
    (4, "Other name of odd length", 2, False, (1, 2)),
    (5, "Second", 0, True, (0, 0)),
    (6, "Button", 5, True, (3, 3)),
]


class ReadTest(unittest.TestCase):
    def test_paths_flags_and_positions_are_read(self):
        asset = ua.SerializedFile(ua.build(OBJECTS))
        self.assertTrue(asset.is_active("Root/Menu/Button"))
        self.assertFalse(asset.is_active("Root/Menu/Other name of odd length"))
        self.assertEqual(asset.position("Root/Menu/Button")[:2], (-5.0, 7.0))
        self.assertEqual(asset.position("Second/Button")[:2], (3.0, 3.0))

    def test_a_file_of_another_format_is_refused(self):
        data = bytearray(ua.build(OBJECTS))
        struct.pack_into(">I", data, 8, 19)
        with self.assertRaises(ua.AssetError):
            ua.SerializedFile(bytes(data))

    def test_a_cut_file_is_refused(self):
        with self.assertRaises(ua.AssetError):
            ua.SerializedFile(ua.build(OBJECTS)[:-10])
        with self.assertRaises(ua.AssetError):
            ua.SerializedFile(b"short")

    def test_a_path_named_twice_cannot_be_edited(self):
        twice = OBJECTS + [(7, "Button", 2, True, (9, 9))]
        asset = ua.SerializedFile(ua.build(twice))
        with self.assertRaises(ua.AssetError):
            asset.hide("Root/Menu/Button")


class EditTest(unittest.TestCase):
    def test_hide_and_move_change_only_their_bytes(self):
        before = ua.build(OBJECTS)
        after = ua.apply(before, [("hide", "Root/Menu/Button"), ("move", "Second/Button", None, -30)])
        self.assertEqual(len(after), len(before))
        asset = ua.SerializedFile(after)
        self.assertFalse(asset.is_active("Root/Menu/Button"))
        # The axis left out keeps its value.
        self.assertEqual(asset.position("Second/Button")[:2], (3.0, -30.0))
        # Nothing else moved: everything else reads as it did.
        self.assertTrue(asset.is_active("Root/Menu"))
        self.assertEqual(asset.position("Root/Menu")[:2], (10.0, 20.0))
        self.assertEqual(sum(a != b for a, b in zip(before, after)), 1 + 2)

    def test_an_object_only_some_versions_have_is_hidden_when_it_is_there(self):
        after = ua.apply(ua.build(OBJECTS), [("hide if there", "Root/Menu/Button"), ("hide if there", "Root/Nothing"),
                                             ("move if there", "Second/Button", -4000, None), ("move if there", "Root/Nothing", 1, 1)])
        asset = ua.SerializedFile(after)
        self.assertFalse(asset.is_active("Root/Menu/Button"))
        self.assertEqual(asset.position("Second/Button")[0], -4000.0)

    def test_an_object_not_in_the_file_is_an_error(self):
        with self.assertRaises(ua.AssetError):
            ua.apply(ua.build(OBJECTS), [("hide", "Root/Nothing")])

    def test_an_unknown_edit_is_an_error(self):
        with self.assertRaises(ua.AssetError):
            ua.apply(ua.build(OBJECTS), [("paint", "Root/Menu")])


if __name__ == "__main__":
    unittest.main()
