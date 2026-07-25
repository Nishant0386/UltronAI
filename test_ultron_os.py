import unittest
import os
import sys

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.security import ActionSecurityGatekeeper, SecurityLevel
from backend.services.llm_provider import MultiLLMRouter
from backend.services.vector_memory import VectorMemoryAgent
from plugins.plugin_manager import PluginManager


class TestUltronOS(unittest.TestCase):
    def test_security_gatekeeper(self):
        """Test ActionSecurityGatekeeper step classification."""
        self.assertEqual(ActionSecurityGatekeeper.classify_action({"type": "run_terminal"}), SecurityLevel.CRITICAL)
        self.assertEqual(ActionSecurityGatekeeper.classify_action({"type": "launch_app"}), SecurityLevel.HIGH)
        self.assertEqual(ActionSecurityGatekeeper.classify_action({"type": "navigate"}), SecurityLevel.MEDIUM)
        self.assertEqual(ActionSecurityGatekeeper.classify_action({"type": "read"}), SecurityLevel.SAFE)

    def test_vector_memory(self):
        """Test VectorMemoryAgent storage and top-K search."""
        vm = VectorMemoryAgent("test_memory.db")
        store_res = vm.store_memory("Tony Stark created JARVIS AI")
        self.assertEqual(store_res["status"], "success")

        results = vm.search_memory("Who built JARVIS?")
        self.assertTrue(len(results) > 0)
        self.assertIn("Tony Stark", results[0]["content"])

        # Clean up test DB
        if os.path.exists("test_memory.db"):
            os.remove("test_memory.db")

    def test_plugin_manager(self):
        """Test PluginManager auto-discovery and tool registry."""
        pm = PluginManager()
        pm.discover_plugins()
        plugins = pm.list_plugins()
        self.assertTrue(len(plugins) >= 3)
        
        # Test executing a safe plugin tool (file search)
        res = pm.execute_tool("file_agent.Search", directory=".", query="requirements.txt")
        self.assertEqual(res["status"], "success")
        self.assertTrue(len(res["matches"]) > 0)


if __name__ == "__main__":
    unittest.main()
