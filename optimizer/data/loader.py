"""Data loading utilities."""

import json
from pathlib import Path
from typing import Dict, List, Optional
from ..models.course import Course, PrerequisiteCondition, PrerequisiteType
from ..models.requirements import (
    Requirement, RequirementType, MajorRequirements, 
    MinorRequirements, EligibilityRequirement
)


class DataLoader:
    """Loads course and requirement data from JSON files."""
    
    def __init__(self, data_dir: Path):
        """
        Initialize the data loader.
        
        Args:
            data_dir: Path to the directory containing data files
        """
        self.data_dir = Path(data_dir)
    
    def load_courses(self, department: str) -> Dict[str, Course]:
        """
        Load courses for a department from JSON file.
        
        Args:
            department: Department code (e.g., "CMSC")
            
        Returns:
            Dictionary mapping course codes to Course objects
        """
        filepath = self.data_dir / "courses" / f"{department}.json"
        
        if not filepath.exists():
            print(f"Warning: Course file not found: {filepath}")
            return {}
        
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        courses = {}
        for course_data in data.get("courses", []):
            course = self._parse_course(course_data)
            courses[course.code] = course
        
        return courses
    
    def load_all_courses(self) -> Dict[str, Course]:
        """Load all courses from all department files."""
        all_courses = {}
        courses_dir = self.data_dir / "courses"
        
        if not courses_dir.exists():
            print(f"Warning: Courses directory not found: {courses_dir}")
            return {}
        
        for filepath in courses_dir.glob("*.json"):
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            for course_data in data.get("courses", []):
                course = self._parse_course(course_data)
                all_courses[course.code] = course
        
        return all_courses
    
    def _parse_course(self, data: Dict) -> Course:
        """Parse course data from JSON."""
        # Parse prerequisites
        prereqs = []
        for prereq_data in data.get("prerequisites", []):
            prereq = self._parse_prerequisite(prereq_data)
            if prereq:
                prereqs.append(prereq)
        
        # Handle gen_eds field (from Testudo scraper) as well as gen_ed_categories
        # New format: gen_eds is a list of lists, e.g., [['DSHS'], ['DSHU', 'DVUP', 'SCIS']]
        # This means: EITHER option 1 OR option 2
        gen_ed_cats = data.get("gen_ed_categories", [])
        gen_ed_opts = []
        
        if "gen_eds" in data:
            # Store the original options structure
            gen_ed_opts = data["gen_eds"]
            
            # For backwards compatibility, also flatten into gen_ed_categories
            # but the optimizer should use gen_ed_options instead
            if not gen_ed_cats:
                gen_ed_cats = []
                for option in data["gen_eds"]:
                    if isinstance(option, list):
                        gen_ed_cats.extend(option)
                    else:
                        # Handle legacy format where it might be a simple string
                        gen_ed_cats.append(option)
        
        return Course(
            code=data["code"],
            name=data["name"],
            credits=data.get("credits", 3),
            description=data.get("description", ""),
            prerequisites=prereqs,
            corequisites=data.get("corequisites", []),
            level=data.get("level", "lower"),
            areas=data.get("areas", []),
            offered=data.get("offered", data.get("semesters_offered", ["Fall", "Spring"])),
            typical_sections=data.get("typical_sections", 1),
            difficulty=data.get("difficulty", 3.0),
            workload_hours=data.get("workload_hours", 10.0),
            gen_ed_categories=gen_ed_cats,
            gen_ed_options=gen_ed_opts,
            restrictions=data.get("restrictions", []),
            notes=data.get("notes", "")
        )
    
    def _parse_prerequisite(self, data) -> Optional[PrerequisiteCondition]:
        """Parse prerequisite condition from JSON."""
        # Handle simple string format (just a course code)
        if isinstance(data, str):
            return PrerequisiteCondition(
                type=PrerequisiteType.COURSE,
                courses=[data],
                min_grade=None
            )
        
        # Handle dictionary format
        if not isinstance(data, dict):
            return None
            
        prereq_type_str = data.get("type", "course")
        
        if prereq_type_str == "course":
            prereq_type = PrerequisiteType.COURSE
            return PrerequisiteCondition(
                type=prereq_type,
                courses=data.get("courses", []),
                min_grade=data.get("min_grade")
            )
        
        elif prereq_type_str == "or":
            prereq_type = PrerequisiteType.OR
            return PrerequisiteCondition(
                type=prereq_type,
                courses=data.get("courses", [])
            )
        
        elif prereq_type_str == "and":
            prereq_type = PrerequisiteType.AND
            conditions = []
            for cond_data in data.get("conditions", []):
                cond = self._parse_prerequisite(cond_data)
                if cond:
                    conditions.append(cond)
            return PrerequisiteCondition(
                type=prereq_type,
                conditions=conditions
            )
        
        return None
    
    def load_major(self, major_code: str) -> Optional[MajorRequirements]:
        """Load major requirements from JSON file."""
        filepath = self.data_dir / "majors" / f"{major_code}.json"
        
        if not filepath.exists():
            print(f"Warning: Major file not found: {filepath}")
            return None
        
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        # Parse requirements
        lower_level = self._parse_requirements(data.get("requirements", {}).get("lower_level_cs", {}))
        upper_level = self._parse_requirements(data.get("requirements", {}).get("upper_level_cs", {}))
        supporting = self._parse_requirements(data.get("requirements", {}).get("math_requirements", {}))
        
        return MajorRequirements(
            major_code=data["major_code"],
            major_name=data["major_name"],
            department=data.get("department", ""),
            degree_type=data.get("degree_type", "BS"),
            lower_level=[lower_level] if lower_level else [],
            upper_level=[upper_level] if upper_level else [],
            supporting_courses=[supporting] if supporting else [],
            min_credits=data.get("min_credits", 120)
        )
    
    def load_minor(self, minor_code: str) -> Optional[MinorRequirements]:
        """Load minor requirements from JSON file."""
        filepath = self.data_dir / "minors" / f"{minor_code}.json"
        
        if not filepath.exists():
            print(f"Warning: Minor file not found: {filepath}")
            return None
        
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        # Parse eligibility
        eligibility_data = data.get("eligibility", {})
        eligibility = EligibilityRequirement(
            min_credits_completed=eligibility_data.get("min_credits_completed"),
            min_gpa=eligibility_data.get("min_gpa"),
            min_semesters_remaining=eligibility_data.get("min_semesters_remaining"),
            allowed_majors=eligibility_data.get("allowed_majors"),
            requires_permission=eligibility_data.get("requires_permission", False),
            application_required=eligibility_data.get("application_required", False)
        )
        
        # Parse core courses
        core_courses = []
        for course_data in data.get("core_courses", []):
            req = Requirement(
                id=course_data["code"],
                name=course_data["name"],
                type=RequirementType.COURSE,
                course_code=course_data["code"],
                min_grade=course_data.get("min_grade")
            )
            core_courses.append(req)
        
        return MinorRequirements(
            minor_code=data["minor_code"],
            minor_name=data["minor_name"],
            department=data.get("department", ""),
            eligibility=eligibility,
            core_courses=core_courses,
            min_credits=data.get("min_credits", 18)
        )
    
    def _parse_requirements(self, data: Dict) -> Optional[Requirement]:
        """Parse requirement from JSON."""
        if not data:
            return None
        
        req_type_str = data.get("type", "group")
        req_type = RequirementType[req_type_str.upper()]
        
        # Extract courses
        courses = []
        for course_data in data.get("courses", []):
            if isinstance(course_data, dict):
                courses.append(course_data.get("code", ""))
            else:
                courses.append(course_data)
        
        return Requirement(
            id=data.get("name", "requirement"),
            name=data.get("name", "Requirement"),
            type=req_type,
            courses=courses,
            min_courses=data.get("min_courses"),
            min_credits=data.get("min_credits")
        )
