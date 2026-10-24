"""B&R inline actions: exactly two buttons and owner-only acknowledgements."""
import sys, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.telegram_ui import markup,authorized_open

class TestBRButtons(unittest.TestCase):
    def test_exactly_two_colored_buttons(self):
        buttons=markup(678,"https://ai-office-miniapp.onrender.com")["inline_keyboard"][0]
        self.assertEqual(len(buttons),2)
        self.assertEqual([(x["text"],x["style"]) for x in buttons],
                         [("Сценарій","danger"),("Я відкрила угоду","success")])
        self.assertEqual(buttons[1]["callback_data"],"br_open:678")
    def test_denies_unauthorized_and_wrong_card(self):
        self.assertEqual(authorized_open("db",678,owner_id=None,actor_id=1,chat_id=-1,expected_chat_id=-1,message_id=8),"DENIED")
        self.assertEqual(authorized_open("db",678,owner_id=2,actor_id=1,chat_id=-1,expected_chat_id=-1,message_id=8),"DENIED")
        with patch("office_bridge._fetchone",return_value=("sig",99)):
            self.assertEqual(authorized_open("db",678,owner_id=1,actor_id=1,chat_id=-1,expected_chat_id=-1,message_id=8),"WRONG_CARD")
    def test_manual_open_is_idempotent(self):
        with patch("office_bridge._fetchone",return_value=("sig",8)),patch("office_br.store.manual_actions",side_effect=[[],["OPENED"]]),patch("office_br.store.record_manual_action",return_value=True) as call:
            arg=dict(owner_id=1,actor_id=1,chat_id=-1,expected_chat_id=-1,message_id=8)
            self.assertEqual(authorized_open("db",678,**arg),"RECORDED")
            self.assertEqual(authorized_open("db",678,**arg),"ALREADY_RECORDED")
            call.assert_called_once_with("db","sig","OPENED")
if __name__=="__main__":unittest.main()
