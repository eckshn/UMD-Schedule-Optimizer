from pathlib import Path
from optimizer.data.loader import DataLoader
from optimizer.core.graph import PrerequisiteGraph
import networkx as nx

# Load courses
loader = DataLoader(Path("sample_data"))
cmsc_courses = loader.load_courses("CMSC")
math_courses = loader.load_courses("MATH")
all_courses = {**cmsc_courses, **math_courses}

# Create graph
graph = PrerequisiteGraph(all_courses)

# Check for cycles
print("Checking for cycles in prerequisite graph...")
has_cycle = graph.has_cycle()
print(f"Has cycles: {has_cycle}")

if has_cycle:
    print("\nFinding cycles...")
    try:
        cycles = list(nx.simple_cycles(graph.graph))
        print(f"Found {len(cycles)} cycle(s):")
        for i, cycle in enumerate(cycles[:10], 1):  # Show first 10
            print(f"\nCycle {i}: {' → '.join(cycle)} → {cycle[0]}")
    except Exception as e:
        print(f"Error finding cycles: {e}")
