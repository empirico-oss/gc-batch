# https://github.com/frequenz-floss/frequenz-repo-config-python/blob/82c1b483ad5a48c259656a6e22c76127e888d55c/src/frequenz/repo/config/mkdocs/mkdocstrings_macros.py

import os
from logging import getLogger
from typing import Any

from mkdocs_macros import plugin as macros

_logger = getLogger(__name__)


def define_env(env: macros.MacrosPlugin) -> None:
    _logger.warning("define_env")

    @env.macro
    def include_file(filename, start_line=0, end_line=None):
        """
        Include a file, optionally indicating start_line and end_line
        (start counting from 0)
        The path is relative to the top directory of the documentation
        project.
        """
        full_filename = os.path.join(env.project_dir, filename)
        with open(full_filename) as f:
            lines = f.readlines()
        line_range = lines[start_line:end_line]
        return "".join(line_range)

    # This needs to be done last
    # Disabled: causes RuntimeError if mkdocstrings isn't fully initialized
    # hook_macros_plugin(env)


def hook_macros_plugin(env: macros.MacrosPlugin) -> None:
    """Integrate the `mkdocs-macros` plugin into `mkdocstrings`.

    This is a temporary workaround to make `mkdocs-macros` work with
    `mkdocstrings` until a proper `mkdocs-macros` *pluglet* is available. See
    https://github.com/mkdocstrings/mkdocstrings/issues/615 for details.

    Args:
        env: The environment to hook the plugin into.
    """
    # get mkdocstrings' Python handler
    python_handler = env.conf["plugins"]["mkdocstrings"].get_handler("python")

    # get the `update_env` method of the Python handler
    update_env = python_handler.update_env

    # override the `update_env` method of the Python handler
    def patched_update_env(config: dict[str, Any]) -> None:
        update_env(config=config)

        # get the `convert_markdown` filter of the env
        convert_markdown = python_handler.env.filters["convert_markdown"]

        # build a chimera made of macros+mkdocstrings
        def render_convert(markdown: str, *args: Any, **kwargs: Any) -> Any:
            return convert_markdown(env.render(markdown), *args, **kwargs)

        # patch the filter
        python_handler.env.filters["convert_markdown"] = render_convert

    _logger.warning("patching update_env")
    # patch the method
    python_handler.update_env = patched_update_env
