# AI Code Sharing Tools - Usage Guide

This document provides instructions on how to use the tools for preparing Python code to share with AI assistants like Claude.

## Overview of Tools

1. **code-stripper.py**: Removes docstrings, comments, and optionally blank lines from Python code
2. **simpler-uml-generator.py**: Creates UML diagrams in both standard and Mermaid formats
3. **prepare-code.sh**: A script that combines the above tools to prepare your entire codebase

## Installation and Setup

### Prerequisites

- Python 3.6 or higher
- For standard UML diagrams: 
  - Graphviz (`apt-get install graphviz` on Debian/Ubuntu)
  - pylint (`pip install pylint`)

### Setup in GitHub Codespaces

1. Clone your repository and open it in Codespaces
2. Install Graphviz if you want standard UML diagrams:
   ```bash
   sudo apt-get update
   sudo apt-get install -y graphviz
   ```
3. Install pylint for pyreverse:
   ```bash
   pip install pylint
   ```
4. Download the three scripts to your workspace:
   - `code-stripper.py`
   - `simpler-uml-generator.py`
   - `prepare-code.sh`
5. Make the bash script executable:
   ```bash
   chmod +x prepare-code.sh
   ```

## Using Individual Tools

### Code Stripper

Strip docstrings and comments from Python files:

```bash
python code-stripper.py [input_dir_or_file] --output [output_dir] [options]
```

Options:
- `--extensions`: Comma-separated list of file extensions to process (default: .py)
- `--keep-blank-lines`: Keep blank lines in the output (removed by default)

Examples:
```bash
# Strip a single file
python code-stripper.py my_script.py --output my_script_stripped.py

# Strip an entire directory
python code-stripper.py my_project/ --output my_project_stripped/

# Strip only .py and .pyx files
python code-stripper.py my_project/ --output my_project_stripped/ --extensions .py,.pyx
```

### UML Diagram Generator

Generate UML class diagrams from Python code:

```bash
python simpler-uml-generator.py [input_dir_or_file] [options]
```

Options:
- `--output-dir`: Directory where diagrams will be saved
- `--format`: Output format (png, svg, pdf) for standard UML diagrams
- `--project-name`: Name of the project (used for filename)
- `--mermaid`: Generate a Mermaid diagram instead of standard UML

Examples:
```bash
# Generate a PNG UML diagram
python simpler-uml-generator.py my_project/ --output-dir diagrams/ --format png

# Generate a Mermaid diagram
python simpler-uml-generator.py my_project/ --output-dir diagrams/ --mermaid

# Generate a UML diagram for a specific file
python simpler-uml-generator.py my_script.py --output-dir diagrams/ --format svg
```

## Using the Combined Preparation Script

The provided bash script combines both tools to prepare your entire codebase:

```bash
./prepare-code.sh [options]
```

Options:
- `-p, --project-dir DIR`: Project directory (default: current directory)
- `-o, --output-dir DIR`: Output directory (default: stripped_code)
- `-f, --format FORMAT`: Diagram format: png, svg, pdf (default: png)
- `--no-uml`: Don't generate standard UML diagrams
- `--no-mermaid`: Don't generate Mermaid diagrams

Example:
```bash
./prepare-code.sh --project-dir nexus_core --output-dir nexus_for_sharing
```

This will:
1. Strip all docstrings and comments from Python files in `nexus_core`
2. Generate both standard UML and Mermaid diagrams
3. Save everything to the `nexus_for_sharing` directory
4. Create a README.md with usage instructions

## Sharing with AI Assistants

After running the preparation script, follow these steps:

1. **Upload the stripped code files** from the `output_dir/code/` directory
2. **Share a UML or Mermaid diagram** for high-level architecture understanding
3. **Reference the original code** if you need to discuss specific docstrings or comments

For Mermaid diagrams, you can copy the content of the `.mmd` file and paste it into a message with triple backticks and the "mermaid" language specifier:

````
```mermaid
classDiagram
    class BaseManager
    BaseManager : +name
    BaseManager : +initialized
    BaseManager : +initialize()
    BaseManager : +shutdown()
    ...
```
````

## Troubleshooting

### Common Issues

1. **Error: Graphviz not found**
   - Install Graphviz: `sudo apt-get install graphviz`
   - Or use the Mermaid option: `--mermaid`

2. **Error: File not found**
   - Ensure all three scripts are in the same directory
   - Check that the input directory exists

3. **Error: Permission denied**
   - Ensure the bash script is executable: `chmod +x prepare-code.sh`

### Getting Help

For each tool, you can display the help information:

```bash
python code-stripper.py --help
python simpler-uml-generator.py --help
./prepare-code.sh --help
```
