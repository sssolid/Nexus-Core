#!/usr/bin/env python3
"""
Script to strip docstrings, comments, and extra whitespace from Python code.
This creates a minimal version of the code that maintains functionality
but removes explanatory text to reduce size.
"""
import os
import re
import ast
import tokenize
import io
from pathlib import Path
import argparse


class DocstringStripper(ast.NodeTransformer):
    """AST Node Transformer that removes docstrings"""
    
    def visit_Module(self, node):
        """Remove module docstrings"""
        if (node.body and isinstance(node.body[0], ast.Expr) and 
                isinstance(node.body[0].value, ast.Str)):
            node.body = node.body[1:]
        return self.generic_visit(node)
    
    def visit_ClassDef(self, node):
        """Remove class docstrings"""
        if (node.body and isinstance(node.body[0], ast.Expr) and 
                isinstance(node.body[0].value, ast.Str)):
            node.body = node.body[1:]
        return self.generic_visit(node)
    
    def visit_FunctionDef(self, node):
        """Remove function/method docstrings"""
        if (node.body and isinstance(node.body[0], ast.Expr) and 
                isinstance(node.body[0].value, ast.Str)):
            node.body = node.body[1:]
        return self.generic_visit(node)
    
    def visit_AsyncFunctionDef(self, node):
        """Remove async function/method docstrings"""
        if (node.body and isinstance(node.body[0], ast.Expr) and 
                isinstance(node.body[0].value, ast.Str)):
            node.body = node.body[1:]
        return self.generic_visit(node)


def remove_comments_and_docstrings(source):
    """
    Returns a string of the source code with comments removed.
    This preserves line numbers by replacing comments with spaces.
    """
    io_obj = io.StringIO(source)
    out = ""
    prev_toktype = tokenize.INDENT
    last_lineno = -1
    last_col = 0

    for tok in tokenize.generate_tokens(io_obj.readline):
        token_type = tok[0]
        token_string = tok[1]
        start_line, start_col = tok[2]
        end_line, end_col = tok[3]
        
        if start_line > last_lineno:
            last_col = 0
        if start_col > last_col:
            out += " " * (start_col - last_col)
        
        # Skip comments
        if token_type == tokenize.COMMENT:
            # Replace with spaces to maintain line numbers
            out += " " * (end_col - start_col)
        # Skip docstrings
        elif token_type == tokenize.STRING:
            if prev_toktype != tokenize.INDENT:
                # This is likely a regular string, not a docstring
                out += token_string
            else:
                # This is likely a docstring, replace with spaces
                out += " " * (end_col - start_col)
        else:
            out += token_string
        
        prev_toktype = token_type
        last_col = end_col
        last_lineno = end_line
    
    return out


def strip_file(file_path, output_path=None, remove_blank_lines=True):
    """
    Process a single file, removing docstrings and comments.
    
    Args:
        file_path: Path to the original file
        output_path: Where to save the stripped file (defaults to same name with _stripped suffix)
        remove_blank_lines: Whether to remove blank/whitespace-only lines
    """
    # Default output path if none provided
    if output_path is None:
        file_stem = Path(file_path).stem
        file_suffix = Path(file_path).suffix
        output_path = str(Path(file_path).with_name(f"{file_stem}_stripped{file_suffix}"))
    
    try:
        # Read the file
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
        
        # First pass: Remove comments while preserving line numbers
        source_without_comments = remove_comments_and_docstrings(source)
        
        # Second pass: Use AST to remove docstrings
        tree = ast.parse(source_without_comments)
        transformer = DocstringStripper()
        transformed_tree = transformer.visit(tree)
        
        # Generate code from the transformed AST
        stripped_code = ast.unparse(transformed_tree)
        
        # Optional: Remove blank lines
        if remove_blank_lines:
            lines = stripped_code.split('\n')
            non_blank_lines = [line for line in lines if line.strip()]
            stripped_code = '\n'.join(non_blank_lines)
        
        # Write the stripped code to the output file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(stripped_code)
        
        return len(source), len(stripped_code)
    except Exception as e:
        print(f"Error processing {file_path}: {str(e)}")
        return 0, 0


def process_directory(input_dir, output_dir, extensions=None, remove_blank_lines=True):
    """
    Process all Python files in a directory, stripping docstrings and comments.
    
    Args:
        input_dir: Directory containing original files
        output_dir: Directory where stripped files will be saved
        extensions: List of file extensions to process (defaults to ['.py'])
        remove_blank_lines: Whether to remove blank lines
    """
    if extensions is None:
        extensions = ['.py']
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    total_original_size = 0
    total_stripped_size = 0
    processed_files = 0
    
    # Walk through the directory tree
    for root, _, files in os.walk(input_dir):
        # Create corresponding directory in output_dir
        rel_path = os.path.relpath(root, input_dir)
        if rel_path == '.':
            current_output_dir = output_dir
        else:
            current_output_dir = os.path.join(output_dir, rel_path)
        os.makedirs(current_output_dir, exist_ok=True)
        
        # Process each file
        for file in files:
            file_ext = os.path.splitext(file)[1]
            if file_ext in extensions:
                input_file = os.path.join(root, file)
                output_file = os.path.join(current_output_dir, file)
                
                original_size, stripped_size = strip_file(
                    input_file, output_file, remove_blank_lines)
                
                if original_size > 0:
                    processed_files += 1
                    total_original_size += original_size
                    total_stripped_size += stripped_size
                    reduction = (1 - stripped_size / original_size) * 100
                    print(f"Processed {input_file} -> {output_file}")
                    print(f"  Size reduced: {original_size} -> {stripped_size} bytes ({reduction:.1f}% reduction)")
    
    # Print summary
    if processed_files > 0:
        overall_reduction = (1 - total_stripped_size / total_original_size) * 100
        print("\nSummary:")
        print(f"  Processed {processed_files} files")
        print(f"  Total size reduced: {total_original_size} -> {total_stripped_size} bytes")
        print(f"  Overall reduction: {overall_reduction:.1f}%")


def main():
    parser = argparse.ArgumentParser(description='Strip docstrings and comments from Python code')
    parser.add_argument('input', help='Input file or directory')
    parser.add_argument('--output', help='Output file or directory (defaults to inputname_stripped)')
    parser.add_argument('--keep-blank-lines', action='store_true', help='Keep blank lines in the output')
    parser.add_argument('--extensions', default='.py', help='Comma-separated list of file extensions to process (default: .py)')
    
    args = parser.parse_args()
    
    input_path = args.input
    output_path = args.output
    extensions = args.extensions.split(',')
    remove_blank_lines = not args.keep_blank_lines
    
    if os.path.isfile(input_path):
        # Process a single file
        original_size, stripped_size = strip_file(input_path, output_path, remove_blank_lines)
        if original_size > 0:
            reduction = (1 - stripped_size / original_size) * 100
            print(f"Size reduced: {original_size} -> {stripped_size} bytes ({reduction:.1f}% reduction)")
    elif os.path.isdir(input_path):
        # Process a directory
        if output_path is None:
            output_path = input_path + '_stripped'
        process_directory(input_path, output_path, extensions, remove_blank_lines)
    else:
        print(f"Input path {input_path} does not exist")


if __name__ == "__main__":
    main()
