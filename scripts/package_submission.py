"""Build and verify an allowlisted source ZIP for the synthetic demo."""
import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    "AGENTS.md", "SPEC.md", "PROGRESS.md", "DECISIONS.md", "README.md",
    "Dockerfile", "docker-compose.yml", ".dockerignore", ".env.example", ".gitignore",
    "pyproject.toml", "requirements.runtime.lock",
}
FRONTEND_FILES = {
    ".env.example", ".dockerignore", "Dockerfile", "package.json", "package-lock.json",
    "tsconfig.json", "next.config.mjs", "postcss.config.mjs", "playwright.config.ts",
    "frontend.test.ts",
}
RULES = {
    "apps/insurance_claims": {".py", ".yaml", ".json"},
    "frontend/app": {".ts", ".tsx", ".css"},
    "frontend/lib": {".ts", ".tsx"},
    "frontend/e2e": {".ts", ".py"},
    "tests": {".py"},
    "evaluation": {".py", ".jsonl", ".json"},
    "docs": {".md", ".png"},
    "scripts": {".py"},
}
FIXTURES = {
    "claim_schema.json", "claims.json", "consent_scenarios.json", "policyholders.json",
    "representatives.json", "required_document_guideline.json",
}


def select():
    files = {ROOT / name for name in ROOT_FILES} | {
        ROOT / "frontend" / name for name in FRONTEND_FILES
    }
    for directory, suffixes in RULES.items():
        for file in (ROOT / directory).rglob("*"):
            if file.suffix in suffixes and file.is_file() and "__pycache__" not in file.parts:
                files.add(file)
    for file in files:
        if file.is_symlink() or not file.is_file() or not file.resolve().is_relative_to(ROOT):
            raise ValueError(f"Invalid submission source: {file.relative_to(ROOT)}")
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/insurance-claims-sop.zip")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    files = select()
    sources = {file.relative_to(ROOT).as_posix(): file for file in files}
    if args.output.resolve() in {file.resolve() for file in files}:
        raise ValueError("The output must not overwrite a submission source file.")
    with ZipFile(args.output, "w", ZIP_DEFLATED) as archive:
        for name, source in sources.items():
            archive.write(source, name)
    with ZipFile(args.output) as archive:
        if archive.testzip() or set(archive.namelist()) != set(sources):
            raise ValueError("Archive verification failed")
        for fixture in FIXTURES:
            name = "apps/insurance_claims/fixtures/" + fixture
            if archive.read(name) != sources[name].read_bytes():
                raise ValueError(f"Fixture changed in archive: {fixture}")
    print(f"Verified {len(files)} archive entries including all six fixtures.")


if __name__ == "__main__":
    main()
