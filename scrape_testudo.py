#!/usr/bin/env python3
"""
Scrape course information from UMD Testudo Schedule of Classes (SOC).
This scraper extracts Gen Ed categories and other detailed course information.

Usage:
    python scrape_testudo.py CMSC MATH STAT
    python scrape_testudo.py --all
    python scrape_testudo.py CMSC --term 202601 --delay 1.5
"""

import requests
from bs4 import BeautifulSoup
import json
import argparse
import time
import re
from pathlib import Path
from typing import Dict, List, Optional, Set


class TestudoScraper:
    """Scraper for UMD Testudo Schedule of Classes"""
    
    BASE_URL = "https://app.testudo.umd.edu/soc"
    
    def __init__(self, term_id: str = "202601", delay: float = 1.0):
        """
        Initialize the scraper.
        
        Args:
            term_id: Semester term ID (e.g., "202601" for Spring 2026)
            delay: Delay in seconds between requests
        """
        self.term_id = term_id
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
    
    def scrape_department(self, dept_code: str) -> Dict:
        """
        Scrape all courses for a department.
        
        Args:
            dept_code: Department code (e.g., "CMSC")
            
        Returns:
            Dictionary with department info and courses
        """
        url = f"{self.BASE_URL}/{self.term_id}/{dept_code.upper()}"
        
        print(f"\n{'='*80}")
        print(f"Scraping {dept_code.upper()} courses from:")
        print(f"  {url}")
        print(f"{'='*80}\n")
        
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"Error fetching {dept_code}: {e}")
            return {"department": dept_code, "courses": []}
        
        soup = BeautifulSoup(response.text, 'html.parser')
        courses = []
        
        # Find all course containers
        course_divs = soup.find_all('div', class_='course')
        
        if not course_divs:
            print(f"Warning: No courses found for {dept_code}")
            return {"department": dept_code, "courses": []}
        
        for course_div in course_divs:
            try:
                course_info = self._parse_course(course_div, dept_code)
                if course_info:
                    courses.append(course_info)
            except Exception as e:
                print(f"Warning: Error parsing course in {dept_code}: {e}")
                continue
        
        print(f"Found {len(courses)} courses for {dept_code}")
        
        return {
            "department": dept_code,
            "term_id": self.term_id,
            "courses": courses
        }
    
    def _parse_course(self, course_div, dept_code: str) -> Optional[Dict]:
        """Parse a single course div element."""
        
        # Get course ID
        course_id_div = course_div.find('div', class_='course-id')
        if not course_id_div:
            return None
        
        course_code = course_id_div.get_text(strip=True)
        
        # Get course title
        course_title_span = course_div.find('span', class_='course-title')
        if not course_title_span:
            return None
        
        course_title = course_title_span.get_text(strip=True)
        
        # Get credits
        credits = None
        credits_span = course_div.find('span', class_='course-min-credits')
        if credits_span:
            credits_text = credits_span.get_text(strip=True)
            try:
                credits = int(credits_text)
            except ValueError:
                # Handle range like "3-4"
                credits = credits_text
        
        # Get Gen Ed codes
        gen_eds = self._extract_gen_eds(course_div)
        
        # Get grading method
        grading_method = None
        grading_span = course_div.find('span', class_='grading-method')
        if grading_span:
            grading_abbr = grading_span.find('abbr')
            if grading_abbr and grading_abbr.get('title'):
                grading_method = grading_abbr.get('title')
        
        # Get course description and prerequisites/corequisites
        description = None
        prerequisites = []
        corequisites = []
        restrictions = []
        
        approved_text_div = course_div.find('div', class_='approved-course-text')
        if approved_text_div:
            full_text = approved_text_div.get_text(separator=' ', strip=True)
            
            # Extract description (first sentence or paragraph usually)
            description = self._extract_description(full_text)
            
            # Extract prerequisites
            prerequisites = self._extract_prerequisites(full_text, dept_code)
            
            # Extract corequisites
            corequisites = self._extract_corequisites(full_text, dept_code)
            
            # Extract restrictions
            restrictions = self._extract_restrictions(full_text)
        
        # Get sections info (to determine if course is offered this semester)
        sections = course_div.find_all('div', class_='section')
        is_offered = len(sections) > 0
        
        course_info = {
            "code": course_code,
            "name": course_title,
            "credits": credits,
            "gen_eds": gen_eds,
            "grading_method": grading_method,
            "description": description,
            "prerequisites": prerequisites,
            "corequisites": corequisites,
            "restrictions": restrictions,
            "is_offered_this_term": is_offered,
            "num_sections": len(sections)
        }
        
        return course_info
    
    def _extract_gen_eds(self, course_div) -> List[str]:
        """
        Extract Gen Ed categories from course div.
        
        Returns a list of Gen Ed options, where each option can be:
        - A single code (string): e.g., "FSAW"
        - A list of codes that must be taken together: e.g., ["DSHU", "DVUP", "SCIS"]
        
        Example: "DSHS or DSHU, DVUP, SCIS" returns [["DSHS"], ["DSHU", "DVUP", "SCIS"]]
        This means: EITHER DSHS alone OR the group (DSHU + DVUP + SCIS)
        """
        gen_eds = []
        
        # Find the gen-ed-codes-group div
        gen_ed_div = course_div.find('div', class_='gen-ed-codes-group')
        if not gen_ed_div:
            return gen_eds
        
        # Get all content including text and spans
        # We need to parse the structure: "CODE1 or CODE2, CODE3, CODE4"
        div_contents = gen_ed_div.find('div')
        if not div_contents:
            return gen_eds
        
        # Extract all gen ed codes in order
        gen_ed_codes = []
        gen_ed_spans = div_contents.find_all('span', class_='course-subcategory')
        for span in gen_ed_spans:
            link = span.find('a')
            if link:
                code = link.get_text(strip=True)
                if code:
                    gen_ed_codes.append(code)
        
        if not gen_ed_codes:
            return gen_eds
        
        # Get the full text to find "or" separators
        full_text = div_contents.get_text()
        
        # Parse the structure by looking for " or " between Gen Ed codes
        # Example: "DSHS or DSHU, DVUP, SCIS" means [["DSHS"], ["DSHU", "DVUP", "SCIS"]]
        # Split into option groups based on "or"
        current_group = []
        search_from = 0  # Track position in text to avoid finding duplicates
        
        for i, code in enumerate(gen_ed_codes):
            current_group.append(code)
            
            # Check if there's " or " after this code (before the next code)
            # We need to look at the text between this code and the next
            if i < len(gen_ed_codes) - 1:
                # Find this code in the text starting from our last position
                code_index = full_text.find(code, search_from)
                if code_index != -1:
                    search_from = code_index + len(code)
                    
                    # Get text after this code until the next code
                    next_code = gen_ed_codes[i + 1]
                    next_code_index = full_text.find(next_code, search_from)
                    
                    if next_code_index != -1:
                        between_text = full_text[search_from:next_code_index]
                        
                        # If "or" appears between them (with word boundaries), end this group
                        # Check for "or" with flexible whitespace
                        if 'or' in between_text.lower().split():
                            gen_eds.append(current_group)
                            current_group = []
        
        # Add the last group
        if current_group:
            gen_eds.append(current_group)
        
        return gen_eds
    
    def _extract_description(self, text: str) -> Optional[str]:
        """Extract course description from full text."""
        # Description is usually before prerequisites/corequisites
        # Split on common keywords
        for keyword in ['Prerequisite:', 'Corequisite:', 'Restriction:', 'Credit only granted for:']:
            if keyword in text:
                text = text.split(keyword)[0]
        
        # Clean up
        text = text.strip()
        
        # If too short, it's probably not a real description
        if len(text) < 20:
            return None
        
        return text
    
    def _extract_prerequisites(self, text: str, dept_code: str) -> List[str]:
        """Extract prerequisite course codes from text."""
        prerequisites = []
        
        # Look for prerequisite section
        prereq_pattern = r'Prerequisite:\s*([^.]+\.)'
        match = re.search(prereq_pattern, text, re.IGNORECASE)
        
        if not match:
            return prerequisites
        
        prereq_text = match.group(1)
        
        # Extract course codes (e.g., CMSC131, MATH140)
        course_pattern = r'\b([A-Z]{4})\s*(\d{3}[A-Z]?)\b'
        matches = re.findall(course_pattern, prereq_text)
        
        for dept, number in matches:
            prerequisites.append(f"{dept}{number}")
        
        return prerequisites
    
    def _extract_corequisites(self, text: str, dept_code: str) -> List[str]:
        """Extract corequisite course codes from text."""
        corequisites = []
        
        # Look for corequisite section
        coreq_pattern = r'Corequisite:\s*([^.]+\.)'
        match = re.search(coreq_pattern, text, re.IGNORECASE)
        
        if not match:
            return corequisites
        
        coreq_text = match.group(1)
        
        # Extract course codes
        course_pattern = r'\b([A-Z]{4})\s*(\d{3}[A-Z]?)\b'
        matches = re.findall(course_pattern, coreq_text)
        
        for dept, number in matches:
            corequisites.append(f"{dept}{number}")
        
        return corequisites
    
    def _extract_restrictions(self, text: str) -> List[str]:
        """Extract enrollment restrictions from text."""
        restrictions = []
        
        # Look for restriction section
        restriction_pattern = r'Restriction:\s*([^.]+\.)'
        match = re.search(restriction_pattern, text, re.IGNORECASE)
        
        if match:
            restrictions.append(match.group(1).strip())
        
        return restrictions
    
    def save_to_json(self, data: Dict, output_dir: str = "testudo_courses"):
        """Save scraped data to JSON file."""
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        
        dept_code = data['department'].lower()
        filepath = output_path / f"{dept_code}.json"
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"✓ Saved to: {filepath}")
    
    def save_to_markdown(self, data: Dict, output_dir: str = "testudo_courses"):
        """Save scraped data to markdown file."""
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        
        dept_code = data['department']
        filepath = output_path / f"{dept_code.lower()}.md"
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"# {dept_code} Courses (Term: {data.get('term_id', 'N/A')})\n\n")
            
            for course in data['courses']:
                f.write(f"## {course['code']}: {course['name']}\n\n")
                
                # Basic info
                if course.get('credits'):
                    f.write(f"**Credits:** {course['credits']}  \n")
                
                if course.get('grading_method'):
                    f.write(f"**Grading:** {course['grading_method']}  \n")
                
                # Gen Eds
                if course.get('gen_eds'):
                    # Format the gen_eds which are now always a list of lists:
                    # [[code1, code2], [code3]] means "(code1, code2) or (code3)"
                    gen_ed_parts = []
                    for gen_ed_group in course['gen_eds']:
                        # Each group is a list of codes
                        gen_ed_parts.append(', '.join(gen_ed_group))
                    
                    # Join with " or " to show the choice
                    f.write(f"**Gen Ed:** {' or '.join(gen_ed_parts)}  \n")
                
                # Offering status
                if course.get('is_offered_this_term'):
                    f.write(f"**Offered:** Yes ({course['num_sections']} sections)  \n")
                else:
                    f.write(f"**Offered:** No  \n")
                
                f.write("\n")
                
                # Description
                if course.get('description'):
                    f.write(f"{course['description']}\n\n")
                
                # Prerequisites
                if course.get('prerequisites'):
                    prereqs_str = ', '.join(course['prerequisites'])
                    f.write(f"**Prerequisites:** {prereqs_str}  \n")
                
                # Corequisites
                if course.get('corequisites'):
                    coreqs_str = ', '.join(course['corequisites'])
                    f.write(f"**Corequisites:** {coreqs_str}  \n")
                
                # Restrictions
                if course.get('restrictions'):
                    for restriction in course['restrictions']:
                        f.write(f"**Restriction:** {restriction}  \n")
                
                f.write("\n---\n\n")
        
        print(f"✓ Saved markdown to: {filepath}")


def load_departments_list(filename: str = "departments.md") -> List[str]:
    """Load department codes from departments.md file."""
    departments = []
    
    try:
        with open(filename, 'r') as f:
            for line in f:
                # Match lines with department codes (4 uppercase letters)
                match = re.match(r'\s+([A-Z]{4})', line)
                if match:
                    departments.append(match.group(1))
    except FileNotFoundError:
        print(f"Warning: {filename} not found")
    
    return departments


def main():
    parser = argparse.ArgumentParser(
        description='Scrape course information from UMD Testudo Schedule of Classes'
    )
    parser.add_argument(
        'departments',
        nargs='*',
        help='Department codes to scrape (e.g., CMSC MATH STAT). Use --all to scrape all departments.'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Scrape all departments from departments.md'
    )
    parser.add_argument(
        '--term',
        default='202601',
        help='Term ID (default: 202601 for Spring 2026)'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=1.0,
        help='Delay between requests in seconds (default: 1.0)'
    )
    parser.add_argument(
        '--output',
        default='testudo_courses',
        help='Output directory (default: testudo_courses)'
    )
    parser.add_argument(
        '--format',
        choices=['json', 'markdown', 'both'],
        default='both',
        help='Output format (default: both)'
    )
    
    args = parser.parse_args()
    
    # Determine which departments to scrape
    if args.all:
        departments = load_departments_list()
        if not departments:
            print("Error: Could not load departments from departments.md")
            return
        print(f"Found {len(departments)} departments to scrape")
    elif args.departments:
        departments = [d.upper() for d in args.departments]
    else:
        parser.print_help()
        return
    
    # Initialize scraper
    scraper = TestudoScraper(term_id=args.term, delay=args.delay)
    
    # Scrape each department
    successful = 0
    failed = []
    
    for i, dept in enumerate(departments, 1):
        print(f"\n[{i}/{len(departments)}] Scraping {dept}...")
        
        data = scraper.scrape_department(dept)
        
        if data['courses']:
            # Save output
            if args.format in ['json', 'both']:
                scraper.save_to_json(data, args.output)
            
            if args.format in ['markdown', 'both']:
                scraper.save_to_markdown(data, args.output)
            
            successful += 1
        else:
            failed.append(dept)
        
        # Rate limiting
        if i < len(departments):
            time.sleep(args.delay)
    
    # Summary
    print(f"\n{'='*80}")
    print(f"SCRAPING COMPLETE")
    print(f"{'='*80}")
    print(f"Successfully scraped: {successful} / {len(departments)} departments")
    
    if failed:
        print(f"\nFailed to scrape: {len(failed)} departments")
        print(f"  {', '.join(failed)}")
    
    print(f"\nOutput saved to: {args.output}/")


if __name__ == '__main__':
    main()
