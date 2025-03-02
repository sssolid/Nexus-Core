#!/bin/bash
# This script prepares your Python codebase for sharing with AI assistants
# by stripping docstrings and comments and generating UML diagrams

# Exit on any error
set -e

# Default values
PROJECT_DIR="."
OUTPUT_DIR="stripped_code"
DIAGRAM_FORMAT="png"
GENERATE_UML=true
GENERATE_MERMAID=true

# Display help
function show_help {
    echo "Usage: $0 [options]"
    echo "Options:"
    echo "  -p, --project-dir DIR    Project directory (default: current directory)"
    echo "  -o, --output-dir DIR     Output directory (default: stripped_code)"
    echo "  -f, --format FORMAT      Diagram format: png, svg, pdf (default: png)"
    echo "  --no-uml                 Don't generate standard UML diagrams"
    echo "  --no-mermaid             Don't generate Mermaid diagrams"
    echo "  -h, --help               Show this help message"
    exit 0
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -p|--project-dir)
            PROJECT_DIR="$2"
            shift 2
            ;;
        -o|--output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        -f|--format)
            DIAGRAM_FORMAT="$2"
            shift 2
            ;;
        --no-uml)
            GENERATE_UML=false
            shift
            ;;
        --no-mermaid)
            GENERATE_MERMAID=false
            shift
            ;;
        -h|--help)
            show_help
            ;;
        *)
            echo "Unknown option: $1"
            show_help
            ;;
    esac
done

# Ensure project directory exists
if [ ! -d "$PROJECT_DIR" ]; then
    echo "Error: Project directory '$PROJECT_DIR' does not exist"
    exit 1
fi

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Get the absolute path of the project and output directories
PROJECT_DIR=$(realpath "$PROJECT_DIR")
OUTPUT_DIR=$(realpath "$OUTPUT_DIR")

echo "=== Preparing code from $PROJECT_DIR ==="
echo "Output will be saved to $OUTPUT_DIR"

# Create diagrams directory
DIAGRAMS_DIR="$OUTPUT_DIR/diagrams"
mkdir -p "$DIAGRAMS_DIR"

# Check if code-stripper.py exists
if [ ! -f "code-stripper.py" ]; then
    echo "Error: code-stripper.py not found in current directory"
    exit 1
fi

# Check if simpler-uml-generator.py exists
if [ ! -f "simpler-uml-generator.py" ]; then
    echo "Error: simpler-uml-generator.py not found in current directory"
    exit 1
fi

# Run the code stripper script
echo "=== Stripping docstrings and comments ==="
python code-stripper.py "$PROJECT_DIR" --output "$OUTPUT_DIR/code" --extensions .py

# Generate standard UML diagram if requested
if [ "$GENERATE_UML" = true ]; then
    echo "=== Generating standard UML class diagrams ==="
    python simpler-uml-generator.py "$PROJECT_DIR" --output-dir "$DIAGRAMS_DIR" --format "$DIAGRAM_FORMAT" --project-name "$(basename "$PROJECT_DIR")"
fi

# Generate Mermaid diagram if requested
if [ "$GENERATE_MERMAID" = true ]; then
    echo "=== Generating Mermaid class diagrams ==="
    python simpler-uml-generator.py "$PROJECT_DIR" --output-dir "$DIAGRAMS_DIR" --mermaid --project-name "$(basename "$PROJECT_DIR")"
fi

# Calculate statistics
ORIGINAL_LINES=$(find "$PROJECT_DIR" -name "*.py" -exec cat {} \; | wc -l)
STRIPPED_LINES=$(find "$OUTPUT_DIR/code" -name "*.py" -exec cat {} \; | wc -l)
REDUCTION=$(( 100 - (STRIPPED_LINES * 100 / ORIGINAL_LINES) ))

# Calculate file size statistics if 'du' is available
ORIGINAL_SIZE=$(du -sh "$PROJECT_DIR" 2>/dev/null | cut -f1 || echo "unknown")
STRIPPED_SIZE=$(du -sh "$OUTPUT_DIR/code" 2>/dev/null | cut -f1 || echo "unknown")

echo "=== Summary ==="
echo "Original code: $ORIGINAL_LINES lines ($ORIGINAL_SIZE)"
echo "Stripped code: $STRIPPED_LINES lines ($STRIPPED_SIZE)"
echo "Line reduction: approximately $REDUCTION%"
echo ""
echo "Diagrams saved to: $DIAGRAMS_DIR"
echo ""

# Create a readme file with usage instructions
README_FILE="$OUTPUT_DIR/README.md"
cat > "$README_FILE" << EOF
# Code Prepared for AI Assistants

This directory contains a stripped-down version of the codebase with docstrings and 
comments removed to reduce size when sharing with AI assistants.

## Contents

- \`code/\`: The stripped code files
- \`diagrams/\`: UML and Mermaid diagrams of the code structure

## How to Use

When working with AI assistants like Claude:

1. **Share the stripped code files** from the \`code/\` directory instead of the original files.
   These maintain all functionality but are much smaller.

2. **Share the diagrams** to provide architectural context:
   - For Mermaid diagrams: Share the \`.mmd\` file contents in a code block with the "mermaid" language tag
   - For standard UML diagrams: Upload the PNG/SVG file directly

3. **Reference the original docstrings** when needed for specific implementation details.

## Size Comparison

- Original code: $ORIGINAL_LINES lines ($ORIGINAL_SIZE)
- Stripped code: $STRIPPED_LINES lines ($STRIPPED_SIZE)
- Reduction: approximately $REDUCTION%

## Generated on: $(date)
EOF

echo "=== Documentation ==="
echo "A README file with usage instructions has been created at $README_FILE"
echo ""
echo "Done! Your code is now ready for sharing with AI assistants."
