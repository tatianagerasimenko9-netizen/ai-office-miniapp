import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br.notification_policy import route_event

class Routing(unittest.TestCase):
    def test_minor_is_silent(self):
        self.assertEqual(route_event("CONFIRMATION_MINOR", status="SENT", original_message_id=123), "SILENT")
    def test_material_edit(self):
        self.assertEqual(route_event("CONFIRMATION_MATERIAL", status="SENT", original_message_id=123, edit_supported=True), "EDIT")
    def test_no_edit_no_duplicate(self):
        self.assertEqual(route_event("CONFIRMATION_MATERIAL", status="SENT", original_message_id=123), "JOURNAL")
    def test_entry_alert(self):
        self.assertEqual(route_event("ENTRY_TOUCHED", status="SENT", original_message_id=123), "ALERT")
    def test_terminal_guard(self):
        self.assertEqual(route_event("TP1", status="SL", original_message_id=123), "JOURNAL")
    def test_gap_not_final(self):
        self.assertEqual(route_event("DATA_GAP", status="SENT", original_message_id=123), "JOURNAL")
if __name__ == "__main__":
    unittest.main()
