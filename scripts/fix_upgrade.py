import sys
from pathlib import Path

path = Path("scripts/upgrade.sh")
if not path.exists():
    print(f"File not found: {path}")
    sys.exit(1)

content = path.read_text(encoding="utf-8")
lines = content.splitlines(keepends=True)

new_lines = []
found = False
for line in lines:
    new_lines.append(line)
    if "find_python() {" in line and not found:
        new_lines.append('  if [[ -f "$VENV_DIR/bin/python3" ]]; then\n')
        new_lines.append('    echo "$VENV_DIR/bin/python3"\n')
        new_lines.append('    return 0\n')
        new_lines.append('  fi\n')
        found = True

path.write_text("".join(new_lines), encoding="utf-8")
print(f"Patched {path}")
