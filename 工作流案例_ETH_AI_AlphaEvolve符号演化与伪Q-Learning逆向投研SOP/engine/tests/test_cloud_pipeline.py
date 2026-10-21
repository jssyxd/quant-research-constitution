import unittest
import os
import json
from strategy_engine.cloud.cloud_pipeline import KagglePipeline, HFModelRegistry, GitHubDeployer

class TestCloudPipeline(unittest.TestCase):
    def test_kaggle_metadata(self):
        kp = KagglePipeline(username="test_user", kernel_slug="test-kernel")
        meta_path = kp.generate_metadata(code_file="train.py", output_dir="/tmp/test_kg")
        self.assertTrue(os.path.exists(meta_path))
        with open(meta_path) as f:
            d = json.load(f)
        self.assertEqual(d['id'], "test_user/test-kernel")
        self.assertEqual(d['enable_gpu'], "true")

    def test_hf_model_card(self):
        hf = HFModelRegistry()
        metrics = {'win_rate': 0.8235, 'sharpe': 0.76, 'calmar': 4.16, 'max_drawdown': 0.1183, 'wfe': 0.72}
        card = hf.generate_model_card(metrics, "(QState (ADD z_score norm_vol))")
        self.assertIn("82.35%", card)
        self.assertIn("QState", card)

    def test_gh_deployer(self):
        gh = GitHubDeployer(repo="jssyxd/strategy")
        cmd = gh.create_model_update_pr_command("model-v4", "Update AST", "Passed 4 gatekeepers")
        self.assertIn("gh pr create", cmd)
        self.assertIn("jssyxd/strategy", cmd)

if __name__ == '__main__':
    unittest.main()
