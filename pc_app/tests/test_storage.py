from __future__ import annotations

import unittest

from kb7studio.storage import HEADER, AtomicSlots, PowerLoss, make_header


class StorageTests(unittest.TestCase):
    def test_a_b_generation_selects_latest(self) -> None:
        slots = AtomicSlots(4096)
        slots.commit(b"first")
        slots.commit(b"second")
        self.assertEqual(slots.active(), b"second")

    def test_power_loss_never_discards_previous_slot(self) -> None:
        for checkpoint in ("erase", "header", "payload"):
            with self.subTest(checkpoint=checkpoint):
                slots = AtomicSlots(4096)
                slots.commit(b"known-good")
                with self.assertRaises(PowerLoss):
                    slots.commit(b"new-data", fail_after=checkpoint)
                self.assertEqual(slots.active(), b"known-good")

    def test_corrupt_active_slot_falls_back(self) -> None:
        slots = AtomicSlots(4096)
        slots.commit(b"one")
        slots.commit(b"two")
        slots.flash[4096 + 64] ^= 1
        self.assertEqual(slots.active(), b"one")

    def test_generation_selection_is_wrap_safe(self) -> None:
        slots = AtomicSlots(4096)
        old, new = b"before-wrap", b"after-wrap"
        slots._program(0, make_header(0x3FFFFFFF, 0xFFFFFFFF, old))
        slots._program(HEADER.size, old)
        slots._program(4096, make_header(0x3FFFFFFF, 0, new))
        slots._program(4096 + HEADER.size, new)
        self.assertEqual(slots.active(), new)


if __name__ == "__main__":
    unittest.main()
