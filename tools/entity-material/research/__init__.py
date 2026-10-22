"""Static IL2CPP research API. Import performs no disk IO or native calls."""
import sys
sys.dont_write_bytecode = True
from .api import Research, validate_output, write_result
