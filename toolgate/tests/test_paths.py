import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from toolgate.core import paths


class RuntimePathsTests(unittest.TestCase):
    def test_data_and_env_paths_can_live_in_persistent_runtime_volume(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(
            os.environ,
            {"TOOLGATE_DATA_DIR": root, "TOOLGATE_ENV_PATH": f"{root}/vault.env"},
        ):
            reloaded = importlib.reload(paths)
            self.assertEqual(str(reloaded.DB_PATH), f"{root}/toolgate.db")
            self.assertEqual(str(reloaded.ENV_PATH), f"{root}/vault.env")
        importlib.reload(paths)


    def test_bootstrap_agent_key_is_idempotent_and_authenticates(self):
        from toolgate.core import control_plane

        with tempfile.TemporaryDirectory() as root, patch.dict(
            os.environ,
            {"TOOLGATE_DATA_DIR": root},
        ):
            importlib.reload(paths)
            reloaded = importlib.reload(control_plane)
            first = reloaded.ensure_bootstrap_agent_key("tgx_test_bootstrap_key_123", ["tool:*"])
            second = reloaded.ensure_bootstrap_agent_key("tgx_test_bootstrap_key_123", ["tool:*"])
            self.assertEqual(first["id"], second["id"])
            self.assertEqual(reloaded.authenticate_agent("tgx_test_bootstrap_key_123")["scopes"], ["tool:*"])
        importlib.reload(paths)
        importlib.reload(control_plane)

    def test_bootstrap_agent_key_updates_deployment_scopes(self):
        from toolgate.core import control_plane

        with tempfile.TemporaryDirectory() as root, patch.dict(
            os.environ,
            {"TOOLGATE_DATA_DIR": root},
        ):
            importlib.reload(paths)
            reloaded = importlib.reload(control_plane)
            first = reloaded.ensure_bootstrap_agent_key("tgx_test_bootstrap_key_123", ["tool:*"])
            second = reloaded.ensure_bootstrap_agent_key("tgx_test_bootstrap_key_123", ["tool:research.*"])
            self.assertEqual(first["id"], second["id"])
            self.assertEqual(reloaded.authenticate_agent("tgx_test_bootstrap_key_123")["scopes"], ["tool:research.*"])
        importlib.reload(paths)
        importlib.reload(control_plane)


    def test_explicit_admin_key_is_persisted_instead_of_replaced(self):
        from toolgate.core import vault

        with tempfile.TemporaryDirectory() as root, patch.dict(
            os.environ,
            {
                "TOOLGATE_DATA_DIR": root,
                "TOOLGATE_ENV_PATH": f"{root}/vault.env",
                "TOOLGATE_ADMIN_KEY": "explicit-admin-key",
            },
        ):
            importlib.reload(paths)
            reloaded = importlib.reload(vault)
            generated = reloaded.ensure_control_keys()
            self.assertEqual(generated, {})
            self.assertEqual(reloaded.get_control_key("TOOLGATE_ADMIN_KEY"), "explicit-admin-key")
            self.assertIn("TOOLGATE_ADMIN_KEY=explicit-admin-key", Path(f"{root}/vault.env").read_text())
        importlib.reload(paths)
        importlib.reload(vault)


if __name__ == "__main__":
    unittest.main()
