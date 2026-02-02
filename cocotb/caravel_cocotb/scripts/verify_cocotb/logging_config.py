"""
Clean logging configuration for caravel_cocotb.

This module provides:
- Color-coded console output for different log levels
- Filtering of verbose/noisy output in normal mode
- Clean test progress and summary formatting
"""

import logging
import sys
import re
from typing import Optional


class Colors:
    """ANSI color codes for terminal output."""
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    DIM = "\033[2m"
    
    # Semantic colors
    INFO = CYAN
    SUCCESS = GREEN
    ERROR = FAIL
    WARN = WARNING
    DEBUG = DIM


class CleanFormatter(logging.Formatter):
    """Custom formatter that applies colors based on log level and filters noise."""
    
    # Patterns to suppress in normal mode (these are noisy docker/simulator outputs)
    SUPPRESS_PATTERNS = [
        r'^-v\s+/.*:.*$',  # Docker volume mounts
        r'^docker\.io/',   # Docker image paths
        r'^WARNING:.*platform.*does not match',  # Docker platform warning
        r'^\s*$',          # Empty lines
    ]
    
    # Patterns that indicate important info vs noise
    IMPORTANT_PATTERNS = [
        r'\[TEST\]',       # Test messages
        r'PASS|FAIL',      # Test results
        r'Error:|Warning:|Critical:',  # Log levels
        r'Test:.*has\s+(passed|failed)',  # Test completion
        r'^\d+\.\d+ns\s+INFO\s+cocotb\.regression',  # Test summary
    ]
    
    LEVEL_COLORS = {
        logging.DEBUG: Colors.DIM,
        logging.INFO: "",
        logging.WARNING: Colors.WARNING,
        logging.ERROR: Colors.FAIL,
        logging.CRITICAL: Colors.FAIL + Colors.BOLD,
    }
    
    def __init__(self, fmt=None, datefmt=None, use_colors=True, verbosity="normal"):
        super().__init__(fmt, datefmt)
        self.use_colors = use_colors and sys.stdout.isatty()
        self.verbosity = verbosity
        self._suppress_re = [re.compile(p) for p in self.SUPPRESS_PATTERNS]
        self._important_re = [re.compile(p) for p in self.IMPORTANT_PATTERNS]
    
    def format(self, record):
        msg = super().format(record)
        
        # Apply level-based colors
        if self.use_colors:
            color = self.LEVEL_COLORS.get(record.levelno, "")
            if color:
                msg = f"{color}{msg}{Colors.ENDC}"
            
            # Highlight important patterns
            if any(p.search(msg) for p in self._important_re):
                if "PASS" in msg or "passed" in msg.lower():
                    msg = msg.replace("PASS", f"{Colors.GREEN}PASS{Colors.ENDC}")
                    msg = msg.replace("passed", f"{Colors.GREEN}passed{Colors.ENDC}")
                elif "FAIL" in msg or "failed" in msg.lower():
                    msg = msg.replace("FAIL", f"{Colors.FAIL}FAIL{Colors.ENDC}")
                    msg = msg.replace("failed", f"{Colors.FAIL}failed{Colors.ENDC}")
        
        return msg
    
    def should_suppress(self, message: str) -> bool:
        """Check if a message should be suppressed based on verbosity."""
        if self.verbosity == "debug":
            return False
        
        # Always suppress docker volume mount spam
        if any(p.search(message) for p in self._suppress_re):
            return True
        
        return False


class OutputFilter(logging.Filter):
    """Filter that suppresses noisy output in normal/quiet modes."""
    
    # Patterns to always suppress (never useful to end users)
    NOISE_PATTERNS = [
        r'^-v\s+/',  # Docker volume mounts building up
        r'^docker\.io/',
        r'What\'s next:',
        r'View a summary of image vulnerabilities',
        r'docker scout',
    ]
    
    def __init__(self, verbosity="normal"):
        super().__init__()
        self.verbosity = verbosity
        self._noise_re = [re.compile(p) for p in self.NOISE_PATTERNS]
    
    def filter(self, record):
        if self.verbosity == "debug":
            return True
        
        msg = record.getMessage()
        
        # Check if it's noise
        for pattern in self._noise_re:
            if pattern.search(msg):
                return False
        
        return True


def setup_logger(name: str, verbosity: str = "normal", log_file: Optional[str] = None) -> logging.Logger:
    """
    Set up a logger with clean formatting.
    
    Args:
        name: Logger name
        verbosity: One of "quiet", "normal", "debug"
        log_file: Optional file path for logging
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    
    # Clear existing handlers
    logger.handlers = []
    
    # Set level based on verbosity
    if verbosity == "quiet":
        logger.setLevel(logging.WARNING)
    elif verbosity == "debug":
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)
    
    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(CleanFormatter(
        fmt="%(message)s",
        use_colors=True,
        verbosity=verbosity
    ))
    console_handler.addFilter(OutputFilter(verbosity))
    logger.addHandler(console_handler)
    
    # File handler (no colors, full output)
    if log_file:
        file_handler = logging.FileHandler(log_file, mode='w')
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        file_handler.setLevel(logging.DEBUG)  # Always log everything to file
        logger.addHandler(file_handler)
    
    return logger


def print_test_header(test_name: str, sim_type: str = "RTL"):
    """Print a clean header for test execution."""
    separator = "=" * 60
    print(f"\n{Colors.CYAN}{separator}{Colors.ENDC}")
    print(f"{Colors.BOLD}Running: {Colors.ENDC}{test_name}")
    print(f"{Colors.DIM}Simulation: {sim_type}{Colors.ENDC}")
    print(f"{Colors.CYAN}{separator}{Colors.ENDC}\n")


def print_test_result(test_name: str, passed: bool, duration: str = "", errors: int = 0, warnings: int = 0):
    """Print a clean test result summary."""
    if passed:
        status = f"{Colors.GREEN}{Colors.BOLD}PASSED{Colors.ENDC}"
        icon = "✓"
    else:
        status = f"{Colors.FAIL}{Colors.BOLD}FAILED{Colors.ENDC}"
        icon = "✗"
    
    print(f"\n{icon} Test: {test_name} {status}")
    if duration:
        print(f"  Duration: {duration}")
    if errors > 0 or warnings > 0:
        print(f"  Errors: {errors}, Warnings: {warnings}")
    print()


def print_summary_table(tests: list, total_duration: str):
    """Print a clean summary table of all test results."""
    passed = sum(1 for t in tests if t.passed == "passed")
    failed = sum(1 for t in tests if t.passed == "failed")
    unknown = len(tests) - passed - failed
    
    separator = "=" * 60
    
    print(f"\n{Colors.CYAN}{separator}{Colors.ENDC}")
    print(f"{Colors.BOLD}Test Summary{Colors.ENDC}")
    print(f"{Colors.CYAN}{separator}{Colors.ENDC}")
    
    # Summary counts
    print(f"\n  Total:   {len(tests)}")
    print(f"  {Colors.GREEN}Passed:  {passed}{Colors.ENDC}")
    if failed > 0:
        print(f"  {Colors.FAIL}Failed:  {failed}{Colors.ENDC}")
    else:
        print(f"  Failed:  {failed}")
    if unknown > 0:
        print(f"  {Colors.WARNING}Unknown: {unknown}{Colors.ENDC}")
    print(f"  Duration: {total_duration}")
    
    # Individual test results
    print(f"\n{Colors.DIM}{'Test':<40} {'Status':<10} {'Duration':<12}{Colors.ENDC}")
    print("-" * 62)
    
    for test in tests:
        if test.passed == "passed":
            status = f"{Colors.GREEN}passed{Colors.ENDC}"
        elif test.passed == "failed":
            status = f"{Colors.FAIL}failed{Colors.ENDC}"
        else:
            status = f"{Colors.WARNING}unknown{Colors.ENDC}"
        
        print(f"{test.full_name:<40} {status:<20} {test.duration:<12}")
    
    print(f"{Colors.CYAN}{separator}{Colors.ENDC}")
