#!/usr/bin/env python3
"""
Simple UML diagram generator using pyreverse and graphviz.
This simplifies the process by running pyreverse as a subprocess rather
than trying to use its internal API.
"""
import os
import sys
import argparse
import subprocess
from pathlib import Path
import tempfile


def check_dependencies():
    """Check if required dependencies are installed."""
    try:
        # Check for pylint/pyreverse
        result = subprocess.run(
            ["pyreverse", "--version"], 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True,
            check=False
        )
        if result.returncode != 0:
            print("pyreverse (part of pylint) is not installed. Please install it with:")
            print("pip install pylint")
            return False
        
        # Check for graphviz (dot)
        result = subprocess.run(
            ["dot", "-V"], 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True,
            check=False
        )
        if result.returncode != 0:
            print("Graphviz (dot) is not installed. Please install it:")
            print("- On Ubuntu/Debian: sudo apt-get install graphviz")
            print("- On macOS: brew install graphviz")
            print("- On Windows: download from https://graphviz.org/download/")
            return False
        
        return True
    except Exception as e:
        print(f"Error checking dependencies: {e}")
        return False


def generate_class_diagram(
    input_path, 
    output_dir=None, 
    output_format="png", 
    project_name=None
):
    """
    Generate a UML class diagram using pyreverse and graphviz.
    
    Args:
        input_path: Path to Python module, package, or file
        output_dir: Directory where the diagram will be saved
        output_format: Output format (png, svg, pdf, etc.)
        project_name: Name of the project (used for filename)
    
    Returns:
        Path to the generated diagram file or None if generation failed
    """
    # Create a temporary directory for intermediate files
    with tempfile.TemporaryDirectory() as temp_dir:
        # Set default project name if not provided
        if not project_name:
            if os.path.isfile(input_path):
                project_name = Path(input_path).stem
            else:
                project_name = Path(input_path).name
        
        # Build pyreverse command
        cmd = [
            "pyreverse",
            "--output-directory", temp_dir,
            "--output", "dot",  # Generate dot files
            "--project", project_name
        ]
        
        # Add input path
        if os.path.isfile(input_path):
            cmd.append(input_path)
        else:
            cmd.append(input_path)
        
        try:
            # Run pyreverse to generate dot files
            print(f"Running: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False
            )
            
            if result.returncode != 0:
                print(f"Error generating diagram: {result.stderr}")
                return None
            
            # Check if dot files were generated
            classes_dot = os.path.join(temp_dir, f"classes_{project_name}.dot")
            packages_dot = os.path.join(temp_dir, f"packages_{project_name}.dot")
            
            if not os.path.exists(classes_dot):
                print(f"No class diagram generated. Check if {input_path} contains valid Python code with classes.")
                return None
            
            # Determine output directory
            if not output_dir:
                output_dir = os.getcwd()
            os.makedirs(output_dir, exist_ok=True)
            
            # Convert dot files to desired format
            classes_output = os.path.join(output_dir, f"classes_{project_name}.{output_format}")
            packages_output = os.path.join(output_dir, f"packages_{project_name}.{output_format}")
            
            # Convert class diagram
            dot_cmd = ["dot", "-T" + output_format, classes_dot, "-o", classes_output]
            print(f"Running: {' '.join(dot_cmd)}")
            subprocess.run(dot_cmd, check=True)
            
            # Convert package diagram if it exists
            if os.path.exists(packages_dot):
                dot_cmd = ["dot", "-T" + output_format, packages_dot, "-o", packages_output]
                print(f"Running: {' '.join(dot_cmd)}")
                subprocess.run(dot_cmd, check=True)
            
            # Return path to the generated class diagram
            return os.path.abspath(classes_output)
            
        except Exception as e:
            print(f"Error generating diagram: {e}")
            return None


def generate_simple_mermaid_diagram(input_path, output_path=None):
    """
    Generate a simple Mermaid class diagram using an AST-based approach.
    
    Args:
        input_path: Path to Python module, package, or file
        output_path: Path where to save the Mermaid diagram
        
    Returns:
        Path to the generated Mermaid file or None if generation failed
    """
    try:
        import ast
        from pathlib import Path
        
        def find_python_files(directory):
            """Find all Python files in a directory."""
            path = Path(directory)
            return list(path.glob('**/*.py'))
        
        # Simple class visitor to extract class information
        class ClassVisitor(ast.NodeVisitor):
            def __init__(self):
                self.classes = {}
                self.current_class = None
            
            def visit_ClassDef(self, node):
                class_name = node.name
                bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
                
                self.classes[class_name] = {
                    "bases": bases,
                    "methods": [],
                    "attributes": []
                }
                
                self.current_class = class_name
                self.generic_visit(node)
                self.current_class = None
            
            def visit_FunctionDef(self, node):
                if self.current_class:
                    self.classes[self.current_class]["methods"].append(node.name)
                self.generic_visit(node)
            
            def visit_Assign(self, node):
                if self.current_class:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            self.classes[self.current_class]["attributes"].append(target.id)
                self.generic_visit(node)
        
        # Prepare the output path
        if output_path is None:
            input_name = Path(input_path).name
            output_path = f"classes_{input_name}.mmd"
        
        # Process files
        mermaid = ["classDiagram"]
        all_classes = {}
        
        # Find files to process
        if os.path.isdir(input_path):
            py_files = find_python_files(input_path)
        else:
            py_files = [Path(input_path)]
        
        # Extract class information from each file
        for py_file in py_files:
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    tree = ast.parse(f.read())
                
                visitor = ClassVisitor()
                visitor.visit(tree)
                
                # Merge with existing classes
                for class_name, info in visitor.classes.items():
                    all_classes[class_name] = info
                    
            except Exception as e:
                print(f"Error processing {py_file}: {e}")
        
        # Generate mermaid syntax for each class
        for class_name, info in all_classes.items():
            mermaid.append(f"    class {class_name}")
            
            # Add attributes
            for attr in info["attributes"]:
                if attr.startswith("_"):
                    mermaid.append(f"    {class_name} : -{attr}")
                else:
                    mermaid.append(f"    {class_name} : +{attr}")
            
            # Add methods
            for method in info["methods"]:
                if method.startswith("_"):
                    mermaid.append(f"    {class_name} : -{method}()")
                else:
                    mermaid.append(f"    {class_name} : +{method}()")
            
        # Add inheritance relationships
        for class_name, info in all_classes.items():
            for base in info["bases"]:
                if base in all_classes and base != "object":
                    mermaid.append(f"    {base} <|-- {class_name}")
        
        # Write diagram to file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(mermaid))
        
        print(f"Generated Mermaid diagram at {output_path}")
        return output_path
            
    except Exception as e:
        print(f"Error generating Mermaid diagram: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description='Generate UML class diagrams from Python code')
    parser.add_argument('input', help='Path to Python module, package, or file')
    parser.add_argument('--output-dir', help='Directory where diagrams will be saved')
    parser.add_argument('--format', default='png', help='Output format (png, svg, pdf)')
    parser.add_argument('--project-name', help='Project name (used for filename)')
    parser.add_argument('--mermaid', action='store_true', help='Generate Mermaid diagram')
    
    args = parser.parse_args()
    
    # Generate the appropriate diagram type
    if args.mermaid:
        # Generate Mermaid diagram
        output_path = args.output_dir
        if output_path:
            os.makedirs(output_path, exist_ok=True)
            output_path = os.path.join(output_path, f"classes_{args.project_name or Path(args.input).name}.mmd")
        
        result = generate_simple_mermaid_diagram(args.input, output_path)
        if not result:
            print("Failed to generate Mermaid diagram")
            sys.exit(1)
    else:
        # Check dependencies
        if not check_dependencies():
            sys.exit(1)
            
        # Generate normal diagram
        result = generate_class_diagram(
            args.input,
            args.output_dir,
            args.format,
            args.project_name
        )
        
        if not result:
            print("Failed to generate class diagram")
            sys.exit(1)
        else:
            print(f"Generated class diagram: {result}")


if __name__ == "__main__":
    main()
