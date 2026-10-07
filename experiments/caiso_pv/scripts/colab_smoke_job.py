"""Execute an isolated random-tensor mathematical smoke on the dedicated T4."""
from pathlib import Path
import subprocess
import sys
import zipfile

archive = Path('/content/caiso_pv_smoke_scripts_20261004_0938.zip')
root = Path('/content/caiso_pv_smoke_20261004_0938')
root.mkdir(exist_ok=False)
with zipfile.ZipFile(archive) as bundle:
    for member in bundle.namelist():
        target = (root / member).resolve()
        if not target.is_relative_to(root.resolve()):
            raise ValueError('Archive path escapes the independent smoke directory')
    bundle.extractall(root)
result = root / 'results' / 'smoke' / 't4_math_only'
process = subprocess.run(
    [sys.executable, str(root / 'scripts' / 'smoke.py'), '--output-dir', str(result)],
    capture_output=True, text=True,
)
(root / 'smoke_stdout.txt').write_text(process.stdout, encoding='utf-8')
(root / 'smoke_stderr.txt').write_text(process.stderr, encoding='utf-8')
print(process.stdout)
if process.returncode:
    print(process.stderr[-6000:])
    raise RuntimeError(f'Mathematical smoke failed: {process.returncode}')
output = root.parent / 'caiso_pv_t4_smoke_results_20261004_0938.zip'
with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
    for path in sorted(root.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            bundle.write(path, path.relative_to(root))
print(f'SMOKE_ONLY archive={output}; not a trained CAISO final model')
