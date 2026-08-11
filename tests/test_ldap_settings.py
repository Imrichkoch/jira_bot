import tempfile
import unittest
import gc
from pathlib import Path

from app.admin_store import AdminStore
from app.ldap_settings import LdapSettingsStore


class LdapSettingsTests(unittest.TestCase):
    def test_local_mode_is_safe_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = LdapSettingsStore(Path(temp_dir)).get()
        self.assertEqual(settings["mode"], "local")
        self.assertEqual(settings["server_url"], "")

    def test_ldap_mode_rejects_incomplete_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LdapSettingsStore(Path(temp_dir))
            with self.assertRaises(ValueError):
                store.update({"mode": "ldap"})

    def test_external_session_is_resolved_as_admin_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AdminStore(Path(temp_dir) / "admin.sqlite3")
            token = store.create_ldap_session(username="alice", display_name="Alice", email="alice@example.test")
            session = store.get_session_admin(token)
            del store
            gc.collect()
        self.assertEqual(session["username"], "alice")
        self.assertEqual(session["auth_source"], "ldap")


if __name__ == "__main__":
    unittest.main()
