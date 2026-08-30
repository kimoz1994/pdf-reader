# gui_app/services/hint_generator.py
"""
This module generates Vimium-style hint labels (A, B, C... AA, AB, AC...).

Key concepts:
- Character sequences: Like counting in base-N
- Generator pattern: Generate labels on demand
"""

from typing import List
from .element_detector import Element

class HintGenerator:
    """
    Generate unique hint labels for elements.
    
    Labels sequence: A, B, C, ... Z, AA, AB, AC, ...
    Similar to Excel column names or Vimium hints.
    """
    
    def __init__(self, chars: str = "ASDFGHJKLWER"):
        """
        Initialize with custom character set.
        
        Args:
            chars: Characters to use for hints (Vimium uses home row)
        """
        self.chars = chars
        self.counter = 0  # Track which label we're on
    
    def generate_label(self) -> str:
        """
        Generate the next hint label.
        
        How it works:
        - First 12 labels: A, B, C, ... (single chars)
        - After that: AA, AB, AC, ... (two chars)
        - Then: AAA, AAB, ... (three chars) if needed
        
        Returns:
            Hint label string (e.g., "A", "AB", "JK")
        """
        n = self.counter
        self.counter += 1
        
        # Single character (0-11)
        if n < len(self.chars):
            return self.chars[n]
        
        # Two characters (12-155)
        elif n < len(self.chars) * len(self.chars):
            first_idx = (n - len(self.chars)) // len(self.chars)
            second_idx = (n - len(self.chars)) % len(self.chars)
            return self.chars[first_idx] + self.chars[second_idx]
        
        # Three+ characters (rare, but handle it)
        else:
            # Fallback: just use counter as string
            return f"E{n}"
    
    def assign_hints(self, elements: List[Element]) -> List[Element]:
        """
        Assign hint labels to a list of elements.
        
        Args:
            elements: List of Element objects
        
        Returns:
            Same list with .hint_label attribute set
        """
        self.counter = 0  # Reset counter
        
        for elem in elements:
            elem.hint_label = self.generate_label()
        
        return elements
    
    def reset(self):
        """Reset counter to start from A again."""
        self.counter = 0


# Test it
if __name__ == "__main__":
    gen = HintGenerator()
    
    # Generate first 15 labels
    for i in range(15):
        print(f"{i}: {gen.generate_label()}")