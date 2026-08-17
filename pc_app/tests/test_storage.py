from __future__ import annotations

import unittest

from kb7studio.storage import AtomicSlots, PowerLoss


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


if __name__ == "__main__":
    unittest.main()
