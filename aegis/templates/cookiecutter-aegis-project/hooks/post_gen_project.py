#!/usr/bin/env python
import os
import shutil
from pathlib import Path

from jinja2 import Environment

PROJECT_DIRECTORY = os.path.realpath(os.path.curdir)


def remove_file(filepath):
    """Removes a file from the generated project."""
    full_path = os.path.join(PROJECT_DIRECTORY, filepath)
    if os.path.exists(full_path):
        os.remove(full_path)


def remove_dir(dirpath):
    """Removes a directory from the generated project."""
    shutil.rmtree(os.path.join(PROJECT_DIRECTORY, dirpath))


def process_j2_templates():
    """
    Process all .j2 template files in the generated project.
    Renders them with cookiecutter context and removes the .j2 originals.
    """
    # Cookiecutter context variables - these template strings are processed
    # by cookiecutter before this hook runs, so they contain actual values
    context = {
        "cookiecutter": {
            "project_name": "{{ cookiecutter.project_name }}",
            "project_slug": "{{ cookiecutter.project_slug }}",
            "project_description": "{{ cookiecutter.project_description }}",
            "author_name": "{{ cookiecutter.author_name }}",
            "author_email": "{{ cookiecutter.author_email }}",
            "version": "{{ cookiecutter.version }}",
            "python_version": "{{ cookiecutter.python_version }}",
            "include_scheduler": "{{ cookiecutter.include_scheduler }}",
            "include_database": "{{ cookiecutter.include_database }}",
            "include_cache": "{{ cookiecutter.include_cache }}",
        }
    }

    # Find all .j2 files in the project
    project_path = Path(PROJECT_DIRECTORY)
    j2_files = list(project_path.rglob("*.j2"))

    for j2_file in j2_files:
        # Read the template content
        with open(j2_file, "r", encoding="utf-8") as f:
            template_content = f.read()

        # Create Jinja2 environment and render the template
        env = Environment()
        template = env.from_string(template_content)
        rendered_content = template.render(context)

        # Write the rendered content to the final file (without .j2 extension)
        output_file = j2_file.with_suffix("")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(rendered_content)

        # Remove the original .j2 file
        j2_file.unlink()

        print(f"Processed template: {j2_file.name} -> {output_file.name}")

        # Ensure file ends with newline
        if not rendered_content.endswith("\n"):
            with open(output_file, "a", encoding="utf-8") as f:
                f.write("\n")


def main():
    """
    Runs the post-generation cleanup to remove files for unselected
    components and process template files.
    """
    # Process .j2 template files first
    process_j2_templates()

    # Remove components not selected
    if "{{ cookiecutter.include_scheduler }}" != "yes":
        remove_file("app/components/scheduler.py")
        remove_file("tests/components/test_scheduler.py")

    if "{{ cookiecutter.include_database }}" != "yes":
        # remove_file("app/services/database_service.py")
        # remove_dir("app/models")
        # remove_dir("alembic")
        pass  # Placeholder for database component

    if "{{ cookiecutter.include_cache }}" != "yes":
        # remove_file("app/services/cache_service.py")
        pass  # Placeholder for cache component


if __name__ == "__main__":
    main()
