# %%
import os


def print_directory_structure(startpath):
    for root, dirs, files in os.walk(startpath, topdown=True):
        # Exclude specific directories
        dirs[:] = [d for d in dirs if d not in ['__pycache__', 'win', '.git', '.vscode']]

        # Print the current directory
        level = root.replace(startpath, '').count(os.sep)
        indent = ' ' * 4 * level
        print(f"{indent}{os.path.basename(root)}/")

        # Print all files in the current directory
        subindent = ' ' * 4 * (level + 1)
        for f in files:
            print(f"{subindent}{f}")


# Replace 'your_directory_path' with the path to the directory you want to print
print_directory_structure('../')

# %%
