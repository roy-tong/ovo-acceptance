from pathlib import Path

from setuptools import find_packages, setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent


class BuildPy(build_py):
    def run(self):
        super().run()
        self.copy_tree(str(ROOT / "contracts"), str(Path(self.build_lib) / "ovo_acceptance" / "contracts"))


setup(
    name="ovo-acceptance",
    version="0.3.0",
    description="Shared task contracts, evidence and case replay for OVO products",
    long_description=(ROOT / "README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    python_requires=">=3.9",
    license="MIT",
    packages=find_packages(exclude=("tests", "tests.*")),
    package_data={"ovo_acceptance": ["contracts/*.json"]},
    cmdclass={"build_py": BuildPy},
    entry_points={"console_scripts": ["ovo-acceptance=ovo_acceptance.cli:main"]},
)
