import unittest
import numpy as np
from strategy_engine.alphaevolve.ast_engine import ASTNode
from strategy_engine.alphaevolve.jit_compiler import evaluate_ast, jit_eval_q_state

class TestAstJit(unittest.TestCase):
    def test_q_state_jit(self):
        r = np.array([1.0, 1.0, 1.0, -1.0, 0.0], dtype=np.float64)
        v = jit_eval_q_state(0.88, 0.12, r)
        self.assertEqual(len(v), 5)
        # First step: 0.88 * 0 + 0.12 * 1.0 = 0.12
        self.assertAlmostEqual(v[0], 0.12, places=6)
        # Second step: 0.88 * 0.12 + 0.12 * 1.0 = 0.1056 + 0.12 = 0.2256
        self.assertAlmostEqual(v[1], 0.2256, places=6)

    def test_ast_evaluation(self):
        # Construct AST: QState(gamma=0.88, alpha=0.12, r=SUB(z_score, norm_volume))
        gamma_node = ASTNode('CONST', value=0.88)
        alpha_node = ASTNode('CONST', value=0.12)
        z_node = ASTNode('FEATURE', feature_name='z_score')
        vol_node = ASTNode('FEATURE', feature_name='norm_volume')
        sub_node = ASTNode('SUB', children=[z_node, vol_node])
        
        q_node = ASTNode('Q_STATE', children=[gamma_node, alpha_node, sub_node])
        
        self.assertEqual(q_node.depth(), 3)
        # q_node (1) + gamma (1) + alpha (1) + sub_node (1) + z_node (1) + vol_node (1) = 6 nodes
        self.assertEqual(q_node.node_count(), 6)
        
        feats = {
            'z_score': np.array([1.0, 2.0, 1.5], dtype=np.float64),
            'norm_volume': np.array([0.5, 0.5, 0.5], dtype=np.float64)
        }
        res = evaluate_ast(q_node, feats, 3)
        self.assertEqual(len(res), 3)
        # r = [0.5, 1.5, 1.0]
        # v[0] = 0.12 * 0.5 = 0.06
        self.assertAlmostEqual(res[0], 0.06, places=6)

    def test_safe_div_zero_protection(self):
        a = ASTNode('CONST', value=10.0)
        b = ASTNode('CONST', value=0.0)
        div_node = ASTNode('SAFE_DIV', children=[a, b])
        res = evaluate_ast(div_node, {}, 5)
        self.assertFalse(np.isnan(res).any())
        self.assertFalse(np.isinf(res).any())

if __name__ == '__main__':
    unittest.main()
