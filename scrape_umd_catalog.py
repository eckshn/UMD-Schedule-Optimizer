#!/usr/bin/env python3
"""
UMD Academic Catalog Web Scraper

Scrapes course information from https://academiccatalog.umd.edu/undergraduate/approved-courses/
Creates markdown files with course descriptions that can be used to generate course JSON data.

Usage:
    python scrape_umd_catalog.py CMSC
    python scrape_umd_catalog.py MATH STAT PHYS
    python scrape_umd_catalog.py --all  # Scrapes common CS-related departments
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Error: Required packages not installed.")
    print("Please run: pip install requests beautifulsoup4")
    sys.exit(1)


class UMDCatalogScraper:
    """Scraper for UMD Academic Catalog course pages."""
    
    BASE_URL = "https://academiccatalog.umd.edu/undergraduate/approved-courses/"
    
    def __init__(self, output_dir: str = "scraped_courses"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
    
    def scrape_department(self, dept_code: str) -> Optional[Dict]:
        """
        Scrape all courses for a given department.
        
        Args:
            dept_code: 4-letter department code (e.g., 'CMSC', 'MATH')
        
        Returns:
            Dictionary containing department info and courses, or None if failed
        """
        url = urljoin(self.BASE_URL, dept_code.lower() + '/')
        print(f"\n{'='*80}")
        print(f"Scraping {dept_code} courses from:")
        print(f"  {url}")
        print(f"{'='*80}\n")
        
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"Error fetching {dept_code}: {e}")
            return None
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract department name from page title
        dept_name = self._extract_department_name(soup, dept_code)
        
        # Find all course blocks
        courses = self._extract_courses(soup, dept_code)
        
        if not courses:
            print(f"Warning: No courses found for {dept_code}")
            return None
        
        print(f"Found {len(courses)} courses for {dept_code}")
        
        return {
            'department_code': dept_code,
            'department_name': dept_name,
            'url': url,
            'courses': courses,
            'total_courses': len(courses)
        }
    
    def _extract_department_name(self, soup: BeautifulSoup, dept_code: str) -> str:
        """Extract the full department name from the page."""
        # Try to find page title or heading
        title = soup.find('h1', class_='page-title')
        if title:
            # Remove the department code from title
            name = title.get_text(strip=True)
            name = re.sub(f'^{dept_code}\\s*-?\\s*', '', name, flags=re.IGNORECASE)
            return name
        
        # Fallback: look for breadcrumb or other headings
        heading = soup.find('h1')
        if heading:
            return heading.get_text(strip=True)
        
        return dept_code
    
    def _extract_courses(self, soup: BeautifulSoup, dept_code: str) -> List[Dict]:
        """Extract all course information from the page."""
        courses = []
        
        # Course blocks are typically in divs with class 'courseblock'
        course_blocks = soup.find_all('div', class_='courseblock')
        
        if not course_blocks:
            # Alternative: look for course blocks in different structure
            # Some pages use different HTML structures
            course_blocks = soup.find_all('div', class_='course')
        
        for block in course_blocks:
            course_info = self._parse_course_block(block, dept_code)
            if course_info:
                courses.append(course_info)
        
        return courses
    
    def _parse_course_block(self, block: BeautifulSoup, dept_code: str) -> Optional[Dict]:
        """Parse a single course block to extract course information."""
        try:
            # Extract course title (e.g., "CMSC131 Object-Oriented Programming I")
            title_elem = block.find('p', class_='courseblocktitle') or block.find('strong')
            if not title_elem:
                return None
            
            title_text = title_elem.get_text(strip=True)
            
            # Parse course code and name
            # Format: "CMSC131 Object-Oriented Programming I. (4 Credits)"
            match = re.match(
                rf'^({dept_code}\s*\d{{3}}[A-Z]?)\s+(.+?)\.\s*\((\d+)\s+Credits?\)',
                title_text,
                re.IGNORECASE
            )
            
            if not match:
                # Try alternative format without period
                match = re.match(
                    rf'^({dept_code}\s*\d{{3}}[A-Z]?)\s+(.+?)\s*\((\d+)\s+Credits?\)',
                    title_text,
                    re.IGNORECASE
                )
            
            if not match:
                print(f"Warning: Could not parse course title: {title_text[:80]}")
                return None
            
            course_code = match.group(1).replace(' ', '')  # Remove spaces in code
            course_name = match.group(2).strip()
            credits = int(match.group(3))
            
            # Extract all paragraph text from the course block (description + prereqs + etc)
            all_text = block.get_text(separator=' ', strip=True)
            
            # Extract course description (first paragraph after title)
            desc_elem = block.find('p', class_='courseblockdesc')
            if not desc_elem:
                # Look for description in next paragraph
                desc_elem = title_elem.find_next_sibling('p')
            
            description = ''
            if desc_elem:
                description = desc_elem.get_text(strip=True)
            
            # Extract prerequisites from all block text (not just description)
            prerequisites = self._extract_prerequisites(all_text, dept_code)
            
            # Extract additional metadata from all block text
            metadata = self._extract_metadata(block, all_text)
            
            return {
                'code': course_code,
                'name': course_name,
                'credits': credits,
                'description': description,
                'prerequisites': prerequisites,
                'corequisites': metadata.get('corequisites', []),
                'restrictions': metadata.get('restrictions', ''),
                'formerly': metadata.get('formerly', ''),
                'cross_listed': metadata.get('cross_listed', [])
            }
        
        except Exception as e:
            print(f"Error parsing course block: {e}")
            return None
    
    def _extract_prerequisites(self, description: str, dept_code: str) -> List[str]:
        """Extract prerequisite course codes from description text."""
        prerequisites = []
        
        # Look for "Prerequisite:" or "Prerequisite(s):" section
        prereq_match = re.search(
            r'Prerequisite(?:s)?:\s*(.+?)(?:\.|;|Corequisite|Restriction|Credit|$)',
            description,
            re.IGNORECASE | re.DOTALL
        )
        
        if not prereq_match:
            return prerequisites
        
        prereq_text = prereq_match.group(1)
        
        # Find all course codes (e.g., CMSC131, MATH140)
        # Pattern: 2-4 letters followed by 3 digits and optional letter
        course_pattern = r'\b([A-Z]{2,4})\s*(\d{3}[A-Z]?)\b'
        
        for match in re.finditer(course_pattern, prereq_text):
            dept = match.group(1)
            number = match.group(2)
            course_code = f"{dept}{number}"
            
            # Only add if not already in list
            if course_code not in prerequisites:
                prerequisites.append(course_code)
        
        return prerequisites
    
    def _extract_metadata(self, block: BeautifulSoup, description: str) -> Dict:
        """Extract additional metadata like corequisites, restrictions, etc."""
        metadata = {}
        
        # Extract corequisites
        coreq_match = re.search(
            r'Corequisite(?:s)?:\s*(.+?)(?:\.|;|Restriction|Credit|$)',
            description,
            re.IGNORECASE
        )
        if coreq_match:
            coreq_text = coreq_match.group(1)
            course_pattern = r'\b([A-Z]{2,4})\s*(\d{3}[A-Z]?)\b'
            coreqs = []
            for match in re.finditer(course_pattern, coreq_text):
                coreqs.append(f"{match.group(1)}{match.group(2)}")
            metadata['corequisites'] = coreqs
        
        # Extract restrictions
        restriction_match = re.search(
            r'Restriction:\s*(.+?)(?:\.|;|Credit|$)',
            description,
            re.IGNORECASE
        )
        if restriction_match:
            metadata['restrictions'] = restriction_match.group(1).strip()
        
        # Extract "Formerly:" information
        formerly_match = re.search(
            r'Formerly:\s*(.+?)(?:\.|;|$)',
            description,
            re.IGNORECASE
        )
        if formerly_match:
            metadata['formerly'] = formerly_match.group(1).strip()
        
        # Extract cross-listed courses
        cross_match = re.search(
            r'Cross-listed with:\s*(.+?)(?:\.|;|$)',
            description,
            re.IGNORECASE
        )
        if cross_match:
            cross_text = cross_match.group(1)
            course_pattern = r'\b([A-Z]{2,4})\s*(\d{3}[A-Z]?)\b'
            cross_listed = []
            for match in re.finditer(course_pattern, cross_text):
                cross_listed.append(f"{match.group(1)}{match.group(2)}")
            metadata['cross_listed'] = cross_listed
        
        return metadata
    
    def save_as_markdown(self, dept_data: Dict, filename: Optional[str] = None) -> Path:
        """Save scraped course data as a markdown file."""
        if filename is None:
            filename = f"{dept_data['department_code'].lower()}.md"
        
        output_path = self.output_dir / filename
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"# {dept_data['department_code']} - {dept_data['department_name']}\n\n")
            f.write(f"**Source:** {dept_data['url']}\n\n")
            f.write(f"**Total Courses:** {dept_data['total_courses']}\n\n")
            f.write(f"---\n\n")
            
            for course in dept_data['courses']:
                f.write(f"## {course['code']}: {course['name']}\n\n")
                f.write(f"**Credits:** {course['credits']}\n\n")
                
                if course['prerequisites']:
                    prereqs = ', '.join(course['prerequisites'])
                    f.write(f"**Prerequisites:** {prereqs}\n\n")
                
                if course['corequisites']:
                    coreqs = ', '.join(course['corequisites'])
                    f.write(f"**Corequisites:** {coreqs}\n\n")
                
                if course['restrictions']:
                    f.write(f"**Restrictions:** {course['restrictions']}\n\n")
                
                if course['cross_listed']:
                    cross = ', '.join(course['cross_listed'])
                    f.write(f"**Cross-listed with:** {cross}\n\n")
                
                if course['formerly']:
                    f.write(f"**Formerly:** {course['formerly']}\n\n")
                
                f.write(f"**Description:**\n\n")
                f.write(f"{course['description']}\n\n")
                f.write(f"---\n\n")
        
        print(f"✓ Saved markdown to: {output_path}")
        return output_path
    
    def save_as_json(self, dept_data: Dict, filename: Optional[str] = None) -> Path:
        """Save scraped course data as a JSON file."""
        if filename is None:
            filename = f"{dept_data['department_code'].lower()}_raw.json"
        
        output_path = self.output_dir / filename
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(dept_data, f, indent=2, ensure_ascii=False)
        
        print(f"✓ Saved JSON to: {output_path}")
        return output_path


def main():
    """Main entry point for the scraper."""
    parser = argparse.ArgumentParser(
        description='Scrape UMD Academic Catalog for course information',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scrape_umd_catalog.py CMSC
  python scrape_umd_catalog.py MATH STAT
  python scrape_umd_catalog.py --all
  python scrape_umd_catalog.py CMSC --format json
  python scrape_umd_catalog.py PHYS --output my_courses
        """
    )
    
    parser.add_argument(
        'departments',
        nargs='*',
        help='Department codes to scrape (e.g., CMSC, MATH, STAT)'
    )
    
    parser.add_argument(
        '--all',
        action='store_true',
        help='Scrape common CS-related departments (CMSC, MATH, STAT, PHYS, ENGL, COMM)'
    )
    
    parser.add_argument(
        '--format',
        choices=['markdown', 'json', 'both'],
        default='both',
        help='Output format (default: both)'
    )
    
    parser.add_argument(
        '--output',
        '-o',
        default='scraped_courses',
        help='Output directory (default: scraped_courses)'
    )
    
    parser.add_argument(
        '--delay',
        type=float,
        default=1.0,
        help='Delay between requests in seconds (default: 1.0)'
    )
    
    args = parser.parse_args()
    
    # Determine which departments to scrape
    if args.all:
        departments = ['CMSC', 'MATH', 'STAT', 'PHYS', 'ENGL', 'COMM', 'ENEE', 'INST']
    elif args.departments:
        departments = [dept.upper() for dept in args.departments]
    else:
        parser.print_help()
        print("\nError: Please specify department codes or use --all")
        sys.exit(1)
    
    # Create scraper
    scraper = UMDCatalogScraper(output_dir=args.output)
    
    print(f"\n{'='*80}")
    print(f"UMD Academic Catalog Scraper")
    print(f"{'='*80}")
    print(f"Departments to scrape: {', '.join(departments)}")
    print(f"Output directory: {args.output}")
    print(f"Output format: {args.format}")
    print(f"Delay between requests: {args.delay}s")
    
    # Scrape each department
    results = []
    for i, dept in enumerate(departments):
        if i > 0:
            time.sleep(args.delay)  # Be polite to the server
        
        dept_data = scraper.scrape_department(dept)
        
        if dept_data:
            results.append(dept_data)
            
            # Save in requested format(s)
            if args.format in ['markdown', 'both']:
                scraper.save_as_markdown(dept_data)
            
            if args.format in ['json', 'both']:
                scraper.save_as_json(dept_data)
    
    # Print summary
    print(f"\n{'='*80}")
    print(f"SCRAPING COMPLETE")
    print(f"{'='*80}")
    print(f"Successfully scraped: {len(results)} / {len(departments)} departments")
    
    for dept_data in results:
        print(f"  ✓ {dept_data['department_code']}: {dept_data['total_courses']} courses")
    
    failed = len(departments) - len(results)
    if failed > 0:
        print(f"\nFailed to scrape: {failed} departments")
    
    print(f"\nOutput saved to: {args.output}/")
    print(f"\nNext steps:")
    print(f"  1. Review the markdown files for accuracy")
    print(f"  2. Use the descriptions to create course JSON files")
    print(f"  3. Add difficulty ratings and semester offerings manually")


if __name__ == '__main__':
    main()
