"""Basketball Edit Master: local fixed-camera basketball editing."""

import os

# Anaconda's MKL and PyTorch ship separate OpenMP runtimes on Windows.
# Sequential MKL avoids loading the second runtime without suppressing errors.
os.environ.setdefault("MKL_THREADING_LAYER", "SEQUENTIAL")

__version__ = "1.0.0"
