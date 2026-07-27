import sys
sys.stdout.reconfigure(encoding='utf-8')
import pvlib
from pvlib.modelchain import ModelChainResult
import dataclasses

# List all fields
if dataclasses.is_dataclass(ModelChainResult):
    for f in dataclasses.fields(ModelChainResult):
        print(f.name)
