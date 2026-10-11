import unittest

import printer_server


class CoreTests(unittest.TestCase):
    def test_crc8_known_payload(self):
        self.assertEqual(printer_server.crc8(b"\x00"), 0)
        self.assertEqual(printer_server.command(0xA3, b"\x00").hex(), "5178a30001000000ff")

    def test_print_row_requires_48_bytes(self):
        with self.assertRaises(ValueError):
            printer_server.print_row(b"short")

    def test_render_rejects_empty_text(self):
        with self.assertRaises(ValueError):
            printer_server.render_text("   ", 24, "left")

    def test_render_rejects_invalid_alignment(self):
        with self.assertRaises(ValueError):
            printer_server.render_text("hello", 24, "diagonal")

    def test_confirmation_token_is_explicit(self):
        self.assertEqual(printer_server.CONFIRMATION_TOKEN, "CONFIRM_PRINT")


if __name__ == "__main__":
    unittest.main()
