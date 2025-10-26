"""Prerequisite graph for course dependencies."""

from typing import Dict, List, Set, Optional
import networkx as nx
from ..models.course import Course, PrerequisiteCondition, PrerequisiteType


class PrerequisiteGraph:
    """Builds and analyzes course prerequisite dependencies."""
    
    def __init__(self, courses: Dict[str, Course]):
        """
        Initialize the prerequisite graph.
        
        Args:
            courses: Dictionary mapping course codes to Course objects
        """
        self.courses = courses
        self.graph = nx.DiGraph()
        self._build_graph()
    
    def _build_graph(self) -> None:
        """Build the directed graph from course prerequisites."""
        # Add all courses as nodes
        for course_code in self.courses:
            self.graph.add_node(course_code)
        
        # Add edges for prerequisites
        for course_code, course in self.courses.items():
            deps = self._extract_prerequisites(course.prerequisites)
            for prereq in deps:
                if prereq in self.courses:
                    # Edge from prerequisite to dependent course
                    self.graph.add_edge(prereq, course_code)
    
    def _extract_prerequisites(self, prereqs: List[PrerequisiteCondition]) -> List[str]:
        """Extract all prerequisite course codes (handles nested AND/OR)."""
        all_prereqs = []
        
        for prereq in prereqs:
            if prereq.type == PrerequisiteType.COURSE:
                if prereq.courses:
                    all_prereqs.extend(prereq.courses)
            elif prereq.type == PrerequisiteType.OR:
                if prereq.courses:
                    # For OR, we need at least one, so include all as potential deps
                    all_prereqs.extend(prereq.courses)
            elif prereq.type == PrerequisiteType.AND:
                if prereq.conditions:
                    for cond in prereq.conditions:
                        all_prereqs.extend(self._extract_prerequisites([cond]))
        
        return all_prereqs
    
    def get_prerequisites(self, course_code: str) -> Set[str]:
        """Get all direct prerequisites for a course."""
        if course_code not in self.graph:
            return set()
        return set(self.graph.predecessors(course_code))
    
    def get_all_prerequisites(self, course_code: str) -> Set[str]:
        """Get all prerequisites (including transitive) for a course."""
        if course_code not in self.graph:
            return set()
        
        # Get all ancestors in the graph
        try:
            return set(nx.ancestors(self.graph, course_code))
        except nx.NetworkXError:
            return set()
    
    def get_dependent_courses(self, course_code: str) -> Set[str]:
        """Get all courses that have this course as a prerequisite."""
        if course_code not in self.graph:
            return set()
        return set(self.graph.successors(course_code))
    
    def topological_sort(self, courses: List[str]) -> List[str]:
        """
        Get a valid ordering of courses respecting prerequisites.
        
        Args:
            courses: List of course codes to order
            
        Returns:
            Topologically sorted list of courses
        """
        # Create subgraph with only the given courses
        subgraph = self.graph.subgraph(courses)
        
        try:
            return list(nx.topological_sort(subgraph))
        except nx.NetworkXError:
            # Graph has cycles - return best effort ordering
            return list(courses)
    
    def has_cycle(self) -> bool:
        """Check if the prerequisite graph has any cycles."""
        return not nx.is_directed_acyclic_graph(self.graph)
    
    def find_cycles(self) -> List[List[str]]:
        """Find all cycles in the prerequisite graph."""
        try:
            cycles = list(nx.simple_cycles(self.graph))
            return cycles
        except nx.NetworkXError:
            return []
    
    def get_course_level(self, course_code: str) -> int:
        """
        Get the level of a course (how deep in the prerequisite chain).
        
        Returns:
            Level (0 = no prerequisites, 1 = direct prereqs only, etc.)
        """
        if course_code not in self.graph:
            return 0
        
        all_prereqs = self.get_all_prerequisites(course_code)
        if not all_prereqs:
            return 0
        
        # Level is the longest path from any root to this course
        max_level = 0
        for prereq in all_prereqs:
            try:
                path_length = nx.shortest_path_length(self.graph, prereq, course_code)
                max_level = max(max_level, path_length)
            except nx.NetworkXNoPath:
                pass
        
        return max_level
    
    def can_take_together(self, course1: str, course2: str, 
                         completed: Set[str]) -> bool:
        """
        Check if two courses can be taken in the same semester.
        
        Args:
            course1: First course code
            course2: Second course code
            completed: Set of already completed courses
            
        Returns:
            True if courses can be taken together
        """
        # Check if one is a prerequisite of the other
        if course2 in self.get_all_prerequisites(course1):
            return False
        if course1 in self.get_all_prerequisites(course2):
            return False
        
        # Check if prerequisites are satisfied
        prereqs1 = self.get_all_prerequisites(course1)
        prereqs2 = self.get_all_prerequisites(course2)
        
        return (prereqs1.issubset(completed) and prereqs2.issubset(completed))
    
    def get_earliest_semester(self, course_code: str, 
                              completed: Set[str],
                              current_semester: int = 0) -> int:
        """
        Get the earliest semester a course can be taken.
        
        Args:
            course_code: Course to check
            completed: Set of completed courses
            current_semester: Current semester index
            
        Returns:
            Earliest semester index (0-based)
        """
        prereqs = self.get_all_prerequisites(course_code)
        if prereqs.issubset(completed):
            return current_semester
        
        # Need to wait until prerequisites are met
        # Simplified: assume each missing prereq takes 1 semester
        missing = prereqs - completed
        return current_semester + len(missing)
