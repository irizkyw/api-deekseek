from mcp.server.fastmcp import FastMCP
import os
from pathlib import Path
from typing import List

# Initialize FastMCP server for local workspace utility tools
mcp = FastMCP("Workspace Tools", version="1.0.0")

@mcp.tool()
def get_file_tree(path: str = ".") -> str:
    """
    Generate a clean ASCII visual directory tree of the project.
    This helps understand the project structure and directory layout recursively.
    
    Args:
        path: Path to the directory (default: ".").
    """
    target_path = Path(path).resolve()
    if not target_path.exists():
        return f"Error: Path '{path}' does not exist."
    if not target_path.is_dir():
        return f"Error: Path '{path}' is not a directory."
        
    ignored_dirs = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', 'env', 'build', 'dist', 'graphify-out'}
    ignored_files = {'.DS_Store', 'Thumbs.db'}
    
    lines = []
    lines.append(f"Directory Tree for: {target_path}")
    
    def walk(directory: Path, prefix: str = "", depth: int = 0):
        if depth > 6:  # Prevent too deep recursion
            lines.append(f"{prefix}└── ... (too deep)")
            return
            
        try:
            items = sorted(list(directory.iterdir()), key=lambda x: (not x.is_dir(), x.name.lower()))
        except PermissionError:
            lines.append(f"{prefix}└── [Permission Denied]")
            return
            
        # Filter items
        filtered_items = []
        for item in items:
            if item.is_dir() and item.name in ignored_dirs:
                continue
            if item.is_file() and item.name in ignored_files:
                continue
            filtered_items.append(item)
            
        count = len(filtered_items)
        for i, item in enumerate(filtered_items):
            is_last = (i == count - 1)
            connector = "└── " if is_last else "├── "
            
            if item.is_dir():
                lines.append(f"{prefix}{connector}{item.name}/")
                new_prefix = prefix + ("    " if is_last else "│   ")
                walk(item, new_prefix, depth + 1)
            else:
                lines.append(f"{prefix}{connector}{item.name}")
                
    walk(target_path)
    return "\n".join(lines)

@mcp.tool()
def list_files_recursive(path: str = ".") -> str:
    """
    Recursively list all file paths in the directory.
    Useful for seeing all code files in a complex project.
    
    Args:
        path: Path to the directory (default: ".").
    """
    target_path = Path(path).resolve()
    if not target_path.exists():
        return f"Error: Path '{path}' does not exist."
        
    ignored_dirs = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', 'env', 'build', 'dist', 'graphify-out'}
    
    file_list = []
    try:
        for root, dirs, files in os.walk(target_path):
            # Exclude ignored directories in-place
            dirs[:] = [d for d in dirs if d not in ignored_dirs]
            
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(target_path)
                file_list.append(str(rel_path).replace("\\", "/"))
    except Exception as e:
        return f"Error walking directory: {e}"
        
    if not file_list:
        return "No files found."
        
    return "\n".join(sorted(file_list))

if __name__ == "__main__":
    mcp.run()
