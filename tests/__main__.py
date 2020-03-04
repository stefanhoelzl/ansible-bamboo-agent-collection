from pathlib import Path
from unittest import TestLoader, TextTestRunner

if __name__ == "__main__":
    test_base = Path(__file__).parent
    test_suite = TestLoader().discover(
        start_dir=test_base, pattern="test_*.py", top_level_dir=test_base.parent
    )
    TextTestRunner(verbosity=2).run(test_suite)
