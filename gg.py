# %%
import os


def read_files_in_directory(directory, extensions, ignore_folders):
    file_contents = []

    for root, dirs, files in os.walk(directory):
        # Modify the dirs list in-place to skip ignored directories
        dirs[:] = [d for d in dirs if d not in ignore_folders]

        for file in files:
            if file.endswith(extensions):
                file_path = os.path.join(root, file)
                with open(file_path, 'r', encoding='utf-8') as f:
                    file_contents.append(f.read())

    return file_contents


def write_to_big_file(file_contents, output_file):
    with open(output_file, 'w', encoding='utf-8') as f:
        for content in file_contents:
            f.write(content)
            f.write('\n\n')  # Add two newlines between each file's content


def main():
    directory = 'app'  # Replace with the path to your folder
    extensions = ('.py')
    ignore_folders = ['ML',
                      'services']  # Add folders to ignore
    output_file = 'big_file.txt'  # The output file name

    file_contents = read_files_in_directory(
        directory, extensions, ignore_folders)
    write_to_big_file(file_contents, output_file)
    print(f"Contents written to {output_file}")


if __name__ == "__main__":
    main()

# %%
