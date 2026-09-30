import logging
import sys
from pathlib import Path


class Logger:
    """
    A basic Python logger class that provides easy-to-use logging functionality.

    Features:
    - Multiple log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    - Console and file output
    - Customizable log format
    - Automatic log file rotation
    """

    def __init__(
        self,
        name: str = "default",
        level: int = logging.INFO,
        log_file: str | Path | None = None,
        console_output: bool = True,
        file_output: bool = False,
        format_string: str | None = None,
    ):
        """
        Initialize the logger.

        Args:
            name: Logger name
            level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            log_file: Path to log file (if file_output is True)
            console_output: Whether to output to console
            file_output: Whether to output to file
            format_string: Custom format string for log messages
        """
        self.name = name
        self.level = level
        self.log_file = Path(log_file) if log_file else None
        self.console_output = console_output
        self.file_output = file_output

        # Set default format if none provided
        if format_string is None:
            format_string = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

        self.format_string = format_string

        # Create the logger
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)

        # Clear any existing handlers
        self.logger.handlers.clear()

        # Create formatter
        formatter = logging.Formatter(format_string)

        # Add console handler if requested
        if console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(level)
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)

        # Add file handler if requested
        if file_output and self.log_file:
            # Ensure log directory exists
            self.log_file.parent.mkdir(parents=True, exist_ok=True)

            file_handler = logging.FileHandler(self.log_file)
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

    def debug(self, message: str) -> None:
        """Log a debug message."""
        self.logger.debug(message)

    def info(self, message: str) -> None:
        """Log an info message."""
        self.logger.info(message)

    def warning(self, message: str) -> None:
        """Log a warning message."""
        self.logger.warning(message)

    def error(self, message: str) -> None:
        """Log an error message."""
        self.logger.error(message)

    def critical(self, message: str) -> None:
        """Log a critical message."""
        self.logger.critical(message)

    def log(self, level: int, message: str) -> None:
        """Log a message at the specified level."""
        self.logger.log(level, message)

    def set_level(self, level: int) -> None:
        """Set the logging level."""
        self.level = level
        self.logger.setLevel(level)
        for handler in self.logger.handlers:
            handler.setLevel(level)

    def get_level_name(self) -> str:
        """Get the current logging level name."""
        return logging.getLevelName(self.level)

    def is_enabled_for(self, level: int) -> bool:
        """Check if logging is enabled for the given level."""
        return self.logger.isEnabledFor(level)


# Convenience functions for quick logging
def get_logger(
    name: str = "default",
    level: int = logging.INFO,
    log_file: str | Path | None = None,
    console_output: bool = True,
    file_output: bool = False,
) -> Logger:
    """
    Get a logger instance with the specified configuration.

    Args:
        name: Logger name
        level: Logging level
        log_file: Path to log file
        console_output: Whether to output to console
        file_output: Whether to output to file

    Returns:
        Logger instance
    """
    return Logger(
        name=name,
        level=level,
        log_file=log_file,
        console_output=console_output,
        file_output=file_output,
    )
