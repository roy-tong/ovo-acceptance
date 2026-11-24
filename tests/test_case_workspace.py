from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from ovo_acceptance import casebook


class CaseWorkspaceTest(unittest.TestCase):
    def test_run_root_uses_registry_workspace(self) -> None:
        registry = Path("/tmp/ovo-ws/ai输出/ovo-真实任务资产库/registry/cases.jsonl")
        args = SimpleNamespace(root=".", run_root="ai输出/ovo-真实任务资产库/runs")
        self.assertEqual(
            Path("/tmp/ovo-ws/ai输出/ovo-真实任务资产库/runs").resolve(),
            casebook._run_root(args, registry),
        )

    def test_absolute_run_root_is_preserved(self) -> None:
        registry = Path("/tmp/ovo-ws/ai输出/ovo-真实任务资产库/registry/cases.jsonl")
        args = SimpleNamespace(root=".", run_root="/tmp/ovo-runs")
        self.assertEqual(Path("/tmp/ovo-runs").resolve(), casebook._run_root(args, registry))


if __name__ == "__main__":
    unittest.main()
