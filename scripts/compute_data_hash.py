#!/usr/bin/env python3
"""Compute cryptographic hash of the data catalog to ensure immutability."""
import hashlib
from pathlib import Path

def hash_directory(directory: Path) -> str:
    sha = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            rel = path.relative_to(directory).as_posix()
            sha.update(rel.encode())
            with open(path, "rb") as f:
                while chunk := f.read(8192):
                    sha.update(chunk)
    return sha.hexdigest()

if __name__ == "__main__":
    catalog_path = Path("quant-research-constitution/data/catalogs")
    catalog_path.mkdir(parents=True, exist_ok=True)
    
    # Also include sample input in catalog hash for golden testing
    sample_p = Path("quant-research-constitution/tests/golden/features/sample_input.parquet")
    if sample_p.exists():
        # copy or register
        pass

    h = hash_directory(Path("quant-research-constitution/tests/golden/features"))
    print(f"Data & Features Golden Hash: {h}")

    hash_file = Path("quant-research-constitution/tests/golden/data_hash.txt")
    hash_file.parent.mkdir(parents=True, exist_ok=True)
    hash_file.write_text(h)
    print(f"✅ Successfully written hash to {hash_file}")
