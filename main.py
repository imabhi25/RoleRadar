#!/usr/bin/env python3
"""
Career Intelligence / Job Analytics Platform (CLI Prototype)
Summarizes job postings from a CSV dataset using Python's standard library.
"""

import argparse
from collections import Counter
import csv
from pathlib import Path
import sys
from typing import Dict, List, Optional, Set

# Canonical names for technical terms and acronyms to ensure consistent display
CANONICAL_SKILL_NAMES: Dict[str, str] = {
    "python": "Python",
    "docker": "Docker",
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "aws": "AWS",
    "sql": "SQL",
    "kubernetes": "Kubernetes",
    "pytorch": "PyTorch",
    "terraform": "Terraform",
    "typescript": "TypeScript",
    "react": "React",
    "linux": "Linux",
    "c++": "C++",
    "graphql": "GraphQL",
    "css": "CSS",
    "html": "HTML",
    "gcp": "GCP",
    "azure": "Azure",
    "java": "Java",
    "javascript": "JavaScript",
    "go": "Go",
    "golang": "Go",
    "rust": "Rust",
    "fastapi": "FastAPI",
    "c#": "C#",
    "ruby": "Ruby",
    "kafka": "Kafka",
    "node.js": "Node.js",
    "nodejs": "Node.js",
    ".net": ".NET",
    "kotlin": "Kotlin",
    "scala": "Scala",
    "swift": "Swift",
    "redis": "Redis",
    "mongodb": "MongoDB",
    "spark": "Spark",
}

CANONICAL_COUNTRY_NAMES: Dict[str, str] = {
    "united states": "United States",
    "usa": "United States",
    "u.s.a.": "United States",
    "united kingdom": "United Kingdom",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "canada": "Canada",
    "germany": "Germany",
}

# Broad geographic regions that must NOT be classified as sovereign countries
BROAD_REGIONS: Set[str] = {
    "north america",
    "south america",
    "latin america",
    "latam",
    "europe",
    "european union",
    "eu",
    "emea",
    "apac",
    "asia pacific",
    "asia",
    "africa",
    "middle east",
    "worldwide",
    "global",
    "americas",
}

REQUIRED_COLUMNS: Set[str] = {
    "job_id",
    "company",
    "title",
    "location",
    "country",
    "skills",
}

# Resolve default CSV location relative to this script file
DEFAULT_DATA_PATH = Path(__file__).resolve().parent / "data" / "sample_jobs.csv"


def normalize_country(country_raw: str) -> str:
    """
    Normalizes a country string:
    - Blank or whitespace-only values are grouped under 'Unknown'.
    - Broad geographic regions (e.g. 'North America', 'Europe') are grouped under 'Unknown'.
    - Values are matched case-insensitively so variations (e.g. 'Canada', 'canada', 'CANADA')
      group together under a readable display name.
    """
    cleaned = country_raw.strip()
    if not cleaned:
        return "Unknown"
    lower = cleaned.lower()
    if lower in BROAD_REGIONS:
        return "Unknown"
    if lower in CANONICAL_COUNTRY_NAMES:
        return CANONICAL_COUNTRY_NAMES[lower]
    return cleaned.title()


def normalize_skill(skill_raw: str) -> str:
    """
    Normalizes surrounding whitespace and capitalization of a skill string.
    Uses canonical casing for known tech terms/acronyms; defaults to Title Case.
    """
    cleaned = skill_raw.strip()
    if not cleaned:
        return ""
    lookup = cleaned.lower()
    if lookup in CANONICAL_SKILL_NAMES:
        return CANONICAL_SKILL_NAMES[lookup]
    # Default normalization for standard terms
    return cleaned.title()


def extract_skills_from_posting(skills_field: str) -> Set[str]:
    """
    Extracts, normalizes, and deduplicates skills from a semicolon-separated string.
    Returns a set to guarantee each skill is counted at most once per posting.
    """
    if not skills_field:
        return set()
    raw_tokens = skills_field.split(";")
    normalized_skills: Set[str] = set()
    for token in raw_tokens:
        norm = normalize_skill(token)
        if norm:
            normalized_skills.add(norm)
    return normalized_skills


def load_job_postings(file_path: Path) -> List[Dict[str, str]]:
    """
    Loads and validates job postings from a CSV file.
    
    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If file is empty, missing required columns, or contains malformed rows.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found at '{file_path}'.")
    if not file_path.is_file():
        raise ValueError(f"Path is not a regular file: '{file_path}'.")

    with file_path.open(mode="r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        
        # Check if file has no header or is completely empty
        if reader.fieldnames is None:
            raise ValueError(f"The dataset at '{file_path}' is completely empty.")

        # Clean header names (strip whitespace and normalize to lowercase)
        fieldnames = {col.strip().lower() for col in reader.fieldnames if col}
        missing_columns = REQUIRED_COLUMNS - fieldnames
        if missing_columns:
            sorted_missing = sorted(list(missing_columns))
            required_sorted = sorted(list(REQUIRED_COLUMNS))
            raise ValueError(
                f"Missing required column(s) in CSV: {', '.join(sorted_missing)}. "
                f"Required columns are: {', '.join(required_sorted)}."
            )

        num_headers = len(reader.fieldnames)
        postings: List[Dict[str, str]] = []
        for row in reader:
            # Reject rows containing more values than headers
            if None in row and row[None]:
                total_values = num_headers + len(row[None])
                raise ValueError(
                    f"Line {reader.line_num}: row contains {total_values} values, "
                    f"which exceeds the header count of {num_headers}."
                )

            # Skip rows where all fields are empty or whitespace
            raw_values = [v.strip() for v in row.values() if v is not None]
            if not any(raw_values):
                continue

            cleaned_row = {
                k.strip().lower(): (v.strip() if v else "")
                for k, v in row.items()
                if k is not None
            }
            cleaned_row["country"] = normalize_country(cleaned_row.get("country", ""))
            postings.append(cleaned_row)

    if not postings:
        raise ValueError(f"The dataset at '{file_path}' contains headers but 0 job postings.")

    return postings


def display_summary(postings: List[Dict[str, str]], source_path: Path) -> None:
    """
    Computes aggregates and prints a formatted summary to stdout.
    """
    total_postings = len(postings)

    # Aggregate postings by country
    country_counter: Counter[str] = Counter(
        job["country"] for job in postings
    )
    sorted_countries = sorted(
        country_counter.items(),
        key=lambda item: (-item[1], item[0].lower()),
    )

    # Aggregate skills (each skill counted at most once per posting)
    skill_counter: Counter[str] = Counter()
    for job in postings:
        skills = extract_skills_from_posting(job.get("skills", ""))
        for skill in skills:
            skill_counter[skill] += 1

    # Sort skills: highest mention count first; alphabetical for ties
    sorted_skills = sorted(
        skill_counter.items(),
        key=lambda item: (-item[1], item[0].lower()),
    )

    print("=" * 66)
    print(" CAREER INTELLIGENCE / JOB ANALYTICS PLATFORM (CLI PROTOTYPE)")
    print(" [FICTIONAL SAMPLE DATA - FOR DEMONSTRATION PURPOSES ONLY]")
    print("=" * 66)
    print(f"Data Source : {source_path}")
    print(f"Total Postings Analyzed: {total_postings}")
    print("=" * 66)
    print()

    # 1. Country breakdown
    print("POSTINGS BY COUNTRY")
    print("-" * 66)
    print(f"{'Country':<32} {'Postings':>12} {'Share (%)':>16}")
    print("-" * 66)
    for country, count in sorted_countries:
        share_pct = (count / total_postings) * 100
        print(f"{country:<32} {count:>12} {share_pct:>15.1f}%")
    print("-" * 66)
    print()

    # 2. Skills ranking
    print("SKILLS RANKED BY POSTING MENTIONS")
    print("(Counted at most once per posting; tied counts sorted alphabetically)")
    print("-" * 66)
    print(f"{'Rank':<6} {'Skill':<30} {'Mentions':>10} {'Frequency (%)':>14}")
    print("-" * 66)
    for rank, (skill, count) in enumerate(sorted_skills, start=1):
        freq_pct = (count / total_postings) * 100
        print(f"#{rank:<5} {skill:<30} {count:>10} {freq_pct:>13.1f}%")
    print("-" * 66)
    print()
    print("Note: All job listings and company names are fictional samples.")
    print("=" * 66)


def main(argv: Optional[List[str]] = None) -> int:
    """
    Main CLI entrypoint.
    """
    parser = argparse.ArgumentParser(
        description="Career Intelligence CLI - Analyze and summarize job postings."
    )
    parser.add_argument(
        "file_path",
        nargs="?",
        default=str(DEFAULT_DATA_PATH),
        help=f"Path to the job postings CSV file (default: {DEFAULT_DATA_PATH})",
    )
    args = parser.parse_args(argv)

    target_path = Path(args.file_path).resolve()
    try:
        postings = load_job_postings(target_path)
        display_summary(postings, target_path)
        return 0
    except (FileNotFoundError, ValueError) as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    except Exception as err:
        print(f"Unexpected error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
