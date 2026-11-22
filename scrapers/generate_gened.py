#!/usr/bin/env python3
"""
Generate GENED.json from scraped Testudo data.
Collects all courses that have Gen Ed requirements.

The committed GENED.json is exactly this script's output: don't hand-edit it.
Policies Testudo doesn't state (Professional Writing after Academic Writing)
are rules in ``optimizer/core/rules.py`` that the loader applies.
"""

import json
import os
from pathlib import Path

def generate_gened_json(input_dir: str = "data/testudo_courses", output_file: str = "sample_data/courses/GENED.json"):
    """Generate GENED.json from all scraped department JSON files."""
    
    input_path = Path(input_dir)
    output_path = Path(output_file)
    
    gened_courses = []
    
    json_files = sorted(input_path.glob("*.json"))
    
    print(f"Processing {len(json_files)} department files...")
    
    for json_file in json_files:
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)
            
            for course in data.get('courses', []):
                if course.get('gen_eds'):
                    gened_courses.append(course)
        
        except Exception as e:
            print(f"Error processing {json_file}: {e}")
    
    print(f"Found {len(gened_courses)} courses with Gen Ed requirements")
    
    output_data = {
        "department": "GENED",
        "courses": gened_courses
    }
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    print(f"✓ Generated {output_file}")
    print(f"  Total courses: {len(gened_courses)}")
    
    gen_ed_counts = {}
    for course in gened_courses:
        for option_group in course['gen_eds']:
            for code in option_group:
                gen_ed_counts[code] = gen_ed_counts.get(code, 0) + 1
    
    print("\nGen Ed category distribution:")
    for code in sorted(gen_ed_counts.keys()):
        print(f"  {code}: {gen_ed_counts[code]} courses")

if __name__ == "__main__":
    generate_gened_json()
