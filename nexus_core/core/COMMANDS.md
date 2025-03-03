pip install -r requirements.txt
sudo apt-get update
sudo apt-get install -y graphviz
chmod +x prepare-script.sh
bash prepare-script.sh --project-dir nexus_core --output-dir nexus_for_sharing
bash prepare-script.sh --project-dir tests --output-dir nexus_tests_for_sharing

pip install pytest
pytest tests -v > pytest_output.txt 2>&1

find . -path "./nexus_for_sharing" -prune -o -path "./.git" -prune -o -print > directory_structure.txt

pip install pytest-cov
pip install pytest-asyncio

[pytest]
markers =
    asyncio: mark an async test that requires an event loop
