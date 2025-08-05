"""Setup script for Jira Search Mirror."""

from setuptools import setup, find_packages

with open("requirements.txt") as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

# Extract just the core dependencies (exclude dev dependencies)
core_requirements = []
in_dev_section = False
for req in requirements:
    if "development dependencies" in req.lower():
        in_dev_section = True
        continue
    if not in_dev_section and req:
        core_requirements.append(req)

setup(
    name="jira-search-mirror",
    version="0.1.0",
    description="Fast local search for Jira issues",
    long_description=open("CLAUDE.md").read(),
    long_description_content_type="text/markdown",
    author="Claude Code",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.8",
    install_requires=core_requirements,
    entry_points={
        "console_scripts": [
            "jira-search=jira_search.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
)